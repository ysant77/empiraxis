"""Haze H1 acquisition: scoped approvals, the bounded ERA5 request and FIRMS source boxes.

Every client here is a fake. No test opens a network connection or reads a credential.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from earthlab.acquire import era5
from earthlab.acquire.gate import ApprovalRefused, CapExceeded, authorize, load_approvals
from earthlab.acquire.run import acquire_era5, acquire_firms
from earthlab.cases.loader import CaseFile, load_case
from earthlab.cases.models import ApprovalAction, HumanApproval, RequestScope, SourceAsset

ROOT = Path(__file__).resolve().parents[1]
CASE = ROOT / "config" / "acquire" / "haze-2015-h1.yaml"
CASE_ID = "haze-2015-h1-sources"
APPROVALS = load_approvals(ROOT / "config" / "approvals")
INSIDE = datetime(2026, 10, 30, tzinfo=UTC)
LATER = datetime(2026, 11, 1, tzinfo=UTC)
SECRET = "SECRET-TOKEN-0000"
SL, PL = "era5-sl-haze-2015", "era5-pl850-haze-2015"
BOXES = {
    "a": "firms-modis-sp-haze-2015-box-a",
    "b": "firms-modis-sp-haze-2015-box-b",
    "c": "firms-modis-sp-haze-2015-box-c",
}


def _live() -> list[HumanApproval]:
    """The recorded approvals with expiry moved out, so end-to-end tests do not age."""
    return [
        a.model_copy(update={"expires_at_utc": datetime(2100, 1, 1, tzinfo=UTC)}) for a in APPROVALS
    ]


def _case(asset_id: str | None = None, **changes: Any) -> CaseFile:
    loaded = load_case(CASE, ROOT)
    if asset_id is None:
        return loaded
    asset = SourceAsset.model_validate({**loaded.assets[asset_id].model_dump(), **changes})
    return CaseFile(case=loaded.case, assets={**loaded.assets, asset_id: asset})


def _scope(
    asset: SourceAsset, variables: tuple[str, ...] = (), levels: tuple[int, ...] = ()
) -> RequestScope:
    assert asset.extent is not None
    return RequestScope(
        product=asset.product,
        extent=asset.extent,
        start=asset.coverage.start,
        end=asset.coverage.end,
        variables=variables,
        pressure_levels_hpa=levels,
    )


def _download(
    asset_id: str, request: RequestScope | None, size: int = 1_000_000, at: datetime = INSIDE
) -> HumanApproval:
    return authorize(
        APPROVALS,
        ApprovalAction.DOWNLOAD,
        CASE_ID,
        asset_id=asset_id,
        request_bytes=size,
        request=request,
        at=at,
    )


class FakeResult:
    def __init__(self, payload: bytes, announced: int | None) -> None:
        self.payload = payload
        self.announced = len(payload) if announced is None else announced
        self.downloaded = False

    @property
    def content_length(self) -> int:
        return self.announced

    def download(self, target: str) -> str:
        self.downloaded = True
        Path(target).write_bytes(self.payload)
        return target


class FakeCds:
    def __init__(self, payload: bytes = b"GRIB-test", announced: int | None = None) -> None:
        self.payload, self.announced = payload, announced
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.results: list[FakeResult] = []

    def retrieve(self, name: str, request: dict[str, Any]) -> FakeResult:
        self.calls.append((name, request))
        self.results.append(FakeResult(self.payload, self.announced))
        return self.results[-1]


def _never() -> era5.CdsClient:
    raise AssertionError("a refused request must not build a CDS client")


# --- approval records -------------------------------------------------------------------


def test_each_approved_asset_passes_its_scoped_gate() -> None:
    case = _case()
    authorize(APPROVALS, ApprovalAction.CONFIRM_STUDY_AREA, CASE_ID, at=INSIDE)
    sl = _scope(case.assets[SL], era5.H1_VARIABLES[era5.SINGLE_LEVELS])
    pl = _scope(case.assets[PL], era5.H1_VARIABLES[era5.PRESSURE_LEVELS], (850,))
    assert _download(SL, sl).approval_id == "haze-2015-h1-download-era5-sl"
    assert _download(PL, pl).approval_id == "haze-2015-h1-download-era5-pl850"
    for letter, asset_id in BOXES.items():
        approval = _download(asset_id, _scope(case.assets[asset_id]))
        assert approval.approval_id == f"haze-2015-h1-download-firms-box-{letter}"


def test_scoped_gate_refuses_everything_outside_the_records() -> None:
    case = _case()
    box_a, box_b = case.assets[BOXES["a"]], case.assets[BOXES["b"]]
    good = _scope(box_a)
    refused = [
        (
            BOXES["a"],
            good.model_copy(update={"product": "FIRMS/VIIRS_SNPP_SP"}),
            1,
            INSIDE,
            "VIIRS",
        ),
        (
            BOXES["a"],
            good.model_copy(update={"start": datetime(2015, 8, 1, tzinfo=UTC)}),
            1,
            INSIDE,
            "period",
        ),
        (BOXES["a"], _scope(box_b), 1, INSIDE, "area differs"),
        (BOXES["a"], good, 7_000_000, INSIDE, "cap"),
        (BOXES["a"], None, 1, INSIDE, "scoped"),
        (BOXES["a"], good, 1, LATER, "not valid at this time"),
        (SL, _scope(case.assets[SL], ("2m_temperature",)), 1, INSIDE, "variables not approved"),
        (
            PL,
            _scope(case.assets[PL], ("u_component_of_wind",), (500,)),
            1,
            INSIDE,
            "levels not approved",
        ),
    ]
    for asset_id, request, size, at, reason in refused:
        with pytest.raises(ApprovalRefused, match=reason):
            _download(asset_id, request, size, at)


def test_unapproved_products_have_no_records() -> None:
    haze = [a for a in APPROVALS if a.case_id == CASE_ID]
    named = " ".join(
        " ".join(a.asset_ids) + (a.scope.product if a.scope else "") for a in haze
    ).lower()
    assert all(word not in named for word in ("viirs", "mcd64a1", "cams"))
    caps = {a.approval_id: a.max_bytes for a in haze if a.action is ApprovalAction.DOWNLOAD}
    firms_total = sum(v or 0 for k, v in caps.items() if "firms" in k)
    assert 5_000_000 <= firms_total <= 25_000_000


# --- ERA5 ----------------------------------------------------------------------------


def test_era5_requests_have_the_approved_shape(tmp_path: Path) -> None:
    fake = FakeCds()
    manifest = acquire_era5(_case(), SL, _live(), tmp_path, client_factory=lambda: fake)
    assert [name for name, _ in fake.calls] == [era5.SINGLE_LEVELS] * 2
    september, october = fake.calls[0][1], fake.calls[1][1]
    assert september["variable"] == list(era5.H1_VARIABLES[era5.SINGLE_LEVELS])
    assert (september["year"], september["month"], october["month"]) == (["2015"], ["09"], ["10"])
    assert (len(september["day"]), len(october["day"])) == (30, 31)
    assert september["time"] == [f"{h:02d}:00" for h in range(24)]
    assert september["area"] == [4.0, 95.0, -6.0, 118.0]
    assert september["data_format"] == "grib" and "pressure_level" not in september
    digest = hashlib.sha256(b"GRIB-test").hexdigest()
    assert [f["sha256"] for f in manifest["files"]] == [digest, digest]
    assert manifest["files"][0]["request"] == september
    assert manifest["approval_id"] == "haze-2015-h1-download-era5-sl"
    assert manifest["retrieved_at_utc"] and manifest["total_bytes"] == 2 * len(b"GRIB-test")
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "era5_sl_2015_09.grib",
        "era5_sl_2015_10.grib",
    ]


def test_era5_pressure_request_asks_for_850_hpa_only(tmp_path: Path) -> None:
    fake = FakeCds()
    acquire_era5(_case(), PL, _live(), tmp_path, client_factory=lambda: fake)
    assert all(request["pressure_level"] == ["850"] for _, request in fake.calls)
    assert fake.calls[0][0] == era5.PRESSURE_LEVELS


@pytest.mark.parametrize(
    ("asset_id", "changes", "kwargs", "reason"),
    [
        (SL, {}, {"variables": ("2m_temperature",)}, "variables"),
        (PL, {}, {"levels": (500,)}, "pressure levels"),
        (
            SL,
            {
                "coverage": {
                    "start": "2015-08-01T00:00:00Z",
                    "end": "2015-11-01T00:00:00Z",
                    "local_zone": "UTC",
                }
            },
            {},
            "period",
        ),
        (
            SL,
            {
                "coverage": {
                    "start": "2015-09-01T06:00:00Z",
                    "end": "2015-11-01T00:00:00Z",
                    "local_zone": "UTC",
                }
            },
            {},
            "00:00 UTC",
        ),
        (
            SL,
            {"extent": {"min_lon": 90.0, "min_lat": -6.0, "max_lon": 118.0, "max_lat": 4.0}},
            {},
            "area",
        ),
        (SL, {"product": "ERA5/reanalysis-era5-land"}, {}, "not an approved ERA5 product"),
    ],
)
def test_era5_refuses_unapproved_requests_before_any_client(
    tmp_path: Path, asset_id: str, changes: dict[str, Any], kwargs: dict[str, Any], reason: str
) -> None:
    with pytest.raises(era5.Era5Refused, match=reason):
        acquire_era5(
            _case(asset_id, **changes), asset_id, _live(), tmp_path, client_factory=_never, **kwargs
        )
    assert not list(tmp_path.iterdir())


def test_era5_without_a_matching_approval_is_refused(tmp_path: Path) -> None:
    others = [a for a in _live() if a.approval_id != "haze-2015-h1-download-era5-sl"]
    with pytest.raises(ApprovalRefused):
        acquire_era5(_case(), SL, others, tmp_path, client_factory=_never)


def test_era5_size_estimate_fits_the_cap() -> None:
    estimate = era5.expected_bytes(era5.H1_VARIABLES[era5.SINGLE_LEVELS], (), era5.H1_BOX, 1464)
    assert estimate == 1464 * 4 * (93 * 41 * 2 + 200)
    assert estimate <= 60_000_000


def test_era5_byte_cap_refuses_before_download(tmp_path: Path) -> None:
    fake = FakeCds(announced=10_000)
    request = era5.monthly_requests(
        ("10m_u_component_of_wind",), (), era5.H1_BOX, era5.H1_START, era5.H1_END
    )[0][1]
    with pytest.raises(CapExceeded, match="announced"):
        era5.fetch_month(fake, era5.SINGLE_LEVELS, request, tmp_path / "x.grib", budget=5_000)
    assert not fake.results[0].downloaded and not list(tmp_path.iterdir())
    short = FakeCds(payload=b"abc", announced=10)
    with pytest.raises(CapExceeded, match="got 3 bytes"):
        era5.fetch_month(short, era5.SINGLE_LEVELS, request, tmp_path / "y.grib", budget=5_000)
    assert not list(tmp_path.iterdir())


def test_missing_credentials_never_echo_a_secret(tmp_path: Path) -> None:
    def broken() -> Any:
        raise Exception(f"Missing/incomplete configuration file: key {SECRET}")

    with pytest.raises(era5.Era5CredentialsMissing) as err:
        era5.client_from_config(broken)
    assert SECRET not in str(err.value) and err.value.__cause__ is None
    with pytest.raises(era5.Era5CredentialsMissing):
        acquire_era5(
            _case(), SL, _live(), tmp_path, client_factory=lambda: era5.client_from_config(broken)
        )
    assert not list(tmp_path.iterdir())


def test_cds_request_errors_never_echo_their_text(tmp_path: Path) -> None:
    class Failing(FakeCds):
        def retrieve(self, name: str, request: dict[str, Any]) -> FakeResult:
            raise RuntimeError(f"403 for token {SECRET}")

    with pytest.raises(RuntimeError, match="licence acceptance") as err:
        acquire_era5(_case(), SL, _live(), tmp_path, client_factory=Failing)
    assert SECRET not in str(err.value)


# --- FIRMS ---------------------------------------------------------------------------


def _firms(body: str, status: int = 200) -> Callable[[], httpx.Client]:
    transport = httpx.MockTransport(lambda request: httpx.Response(status, text=body))
    return lambda: httpx.Client(transport=transport)


@pytest.mark.parametrize("letter", sorted(BOXES))
def test_each_firms_box_downloads_under_its_record(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, letter: str
) -> None:
    monkeypatch.setenv("FIRMS_API_KEY", SECRET)
    asset_id = BOXES[letter]
    manifest = acquire_firms(
        _case(),
        asset_id,
        _live(),
        tmp_path,
        client_factory=_firms("latitude,longitude\n0.0,101.0\n"),
    )
    assert manifest["approval_id"] == f"haze-2015-h1-download-firms-box-{letter}"
    assert manifest["files"][0]["requests"] == 14 and manifest["files"][0]["rows"] == 14
    assert SECRET not in json.dumps(manifest)


@pytest.mark.parametrize(
    ("changes", "reason"),
    [
        ({"product": "FIRMS/VIIRS_SNPP_SP"}, "VIIRS"),
        (
            {
                "coverage": {
                    "start": "2015-08-01T00:00:00Z",
                    "end": "2015-11-01T00:00:00Z",
                    "local_zone": "UTC",
                }
            },
            "period",
        ),
        (
            {"extent": {"min_lon": 95.0, "min_lat": -1.5, "max_lon": 103.5, "max_lat": 2.0}},
            "area differs",
        ),
    ],
)
def test_firms_refuses_viirs_other_dates_and_other_boxes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, changes: dict[str, Any], reason: str
) -> None:
    monkeypatch.setenv("FIRMS_API_KEY", SECRET)
    case = _case(BOXES["a"], **changes)
    with pytest.raises(ApprovalRefused, match=reason):
        acquire_firms(case, BOXES["a"], _live(), tmp_path, client_factory=_firms("latitude\n"))


def test_firms_oversized_reply_is_deleted(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FIRMS_API_KEY", SECRET)
    body = "latitude,longitude\n" + "1.0,101.0\n" * 50_000  # 0.5 MB x 14 requests > 6 MB cap
    with pytest.raises(CapExceeded):
        acquire_firms(_case(), BOXES["a"], _live(), tmp_path, client_factory=_firms(body))
    assert not list(tmp_path.iterdir())


def test_firms_errors_keep_the_key_redacted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("FIRMS_API_KEY", SECRET)
    with pytest.raises(RuntimeError) as err:
        acquire_firms(
            _case(),
            BOXES["b"],
            _live(),
            tmp_path,
            client_factory=_firms(f"Invalid MAP_KEY {SECRET}", 400),
        )
    assert SECRET not in str(err.value) and "<MAP_KEY>" in str(err.value)


def test_client_and_scope_edge_cases() -> None:
    fake = FakeCds()
    assert era5.client_from_config(lambda: fake) is fake
    with pytest.raises(era5.Era5Refused, match="dataset reanalysis-era5-land is not approved"):
        era5.check_h1("reanalysis-era5-land", ("x",), (), era5.H1_BOX, era5.H1_START, era5.H1_END)
    with pytest.raises(ValueError, match="scope end must be after scope start"):
        RequestScope(
            product="FIRMS/MODIS_SP",
            extent=era5.H1_BOX,
            start=era5.H1_END,
            end=era5.H1_START,
        )
