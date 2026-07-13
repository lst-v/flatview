from __future__ import annotations

from flatview.analytics import annotate_segments, flag_outliers_iqr
from flatview.html_report import render_report


def test_render_report_writes_file_with_charts(tmp_path, make_listing):
    listings = [
        make_listing(id=i, title=f"3i byt {i}", price=100_000 + i * 5_000, area=55)
        for i in range(8)
    ]
    annotate_segments(listings)
    flag_outliers_iqr(listings)

    out = tmp_path / "report.html"
    render_report(
        listings,
        query="3i byt",
        location="Michalovce",
        sources=["bazos.sk"],
        out_path=out,
    )

    text = out.read_text(encoding="utf-8")
    assert "flatview report" in text
    assert "plotly" in text.lower()
    assert "Median (P50)" in text


def test_render_report_two_sided_outliers(tmp_path, make_listing):
    listings = [
        make_listing(id=i, title=f"3i byt {i}", price=100_000 + i * 2_000, area=55)
        for i in range(8)
    ]
    listings.append(make_listing(id=90, title="lacný byt", price=10_000, area=55))
    listings.append(make_listing(id=91, title="drahý byt", price=900_000, area=55))
    annotate_segments(listings)
    flag_outliers_iqr(listings)

    out = tmp_path / "report.html"
    render_report(listings, query="", location="", sources=["bazos.sk"], out_path=out)

    text = out.read_text(encoding="utf-8")
    assert "Potential bargains" in text
    assert "Overpriced" in text
    assert "class='bargain'" in text
    assert "class='overpriced'" in text


def test_render_report_cma_mode(tmp_path, make_listing):
    listings = [
        make_listing(id=i, title=f"3i byt {i}", price=80_000 + i * 4_000, area=50 + i)
        for i in range(8)
    ]
    annotate_segments(listings)
    out = tmp_path / "report_cma.html"
    render_report(
        listings,
        query="3i byt",
        location="Michalovce",
        sources=["bazos.sk"],
        out_path=out,
        mode="cma",
        cma_target_area=55,
    )
    text = out.read_text(encoding="utf-8")
    assert "CMA" in text
    assert "Recommended range" in text
