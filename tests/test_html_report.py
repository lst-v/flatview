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
    assert "flat<span>view</span>" in text  # wordmark header
    assert "plotly" in text.lower()
    assert "Median (P50)" in text
    assert ">Count<" not in text  # sample sizes are a caption, not a stat row
    assert "8 listings · 8 priced · 8 with €/m²" in text

    # Charts need explicit pixel heights — 100% collapses inside auto-height
    # cards — and exactly one CDN script tag (on the first chart).
    n_charts = text.count("plotly-graph-div")
    assert n_charts >= 3
    assert text.count("height:420px") == n_charts
    assert "height:100%" not in text
    assert text.count("cdn.plot.ly") == 1


def test_stats_caption_counts_partial_data(tmp_path, make_listing):
    listings = [
        make_listing(id=i, title=f"byt {i}", price=100_000 + i * 1_000, area=55) for i in range(5)
    ]
    listings.append(make_listing(id=90, title="bez ceny", price=None))
    listings.append(make_listing(id=91, title="bez plochy", price=120_000, area=None))
    annotate_segments(listings)

    out = tmp_path / "report.html"
    render_report(listings, query="", location="", sources=["bazos.sk"], out_path=out)
    assert "7 listings · 6 priced · 5 with €/m²" in out.read_text(encoding="utf-8")


def test_single_segment_breakdown_hidden(tmp_path, make_listing):
    # All resale: a "Resale" table would just repeat "Overall".
    listings = [
        make_listing(id=i, title=f"Po rekonštrukcii byt {i}", price=100_000, area=55)
        for i in range(5)
    ]
    annotate_segments(listings)
    out = tmp_path / "seg1.html"
    render_report(listings, query="", location="", sources=["bazos.sk"], out_path=out)
    text = out.read_text(encoding="utf-8")
    assert "Overall" in text
    assert "Resale" not in text

    # Two segments: the breakdown is a real comparison — show it.
    listings += [
        make_listing(id=10 + i, title=f"Novostavba {i}", price=160_000, area=55) for i in range(5)
    ]
    annotate_segments(listings)
    out2 = tmp_path / "seg2.html"
    render_report(listings, query="", location="", sources=["bazos.sk"], out_path=out2)
    text2 = out2.read_text(encoding="utf-8")
    assert "Resale" in text2 and "New build" in text2


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
    assert "±25%" in text  # default band
    assert "asking prices" in text  # disclaimer: asking ≠ transaction prices
    assert text.index("CMA") < text.index("Statistics")  # recommendation leads


def test_render_report_cma_segment_filter(tmp_path, make_listing):
    resale = [
        make_listing(id=i, title=f"Po rekonštrukcii byt {i}", price=90_000 + i * 1_000, area=54 + i)
        for i in range(5)
    ]
    new_build = [
        make_listing(id=10 + i, title=f"Novostavba {i}", price=160_000 + i * 1_000, area=54 + i)
        for i in range(5)
    ]
    listings = resale + new_build
    annotate_segments(listings)
    out = tmp_path / "cma_seg.html"
    render_report(
        listings,
        query="byt",
        location="MI",
        sources=["bazos.sk"],
        out_path=out,
        mode="cma",
        cma_target_area=55,
        cma_segment="resale",
    )
    text = out.read_text(encoding="utf-8")
    assert "restricted to the <strong>resale</strong> segment" in text
    assert "Novostavba" not in text.split("Top comparables")[1].split("</table>")[0]


def test_render_report_cma_segment_fallback(tmp_path, make_listing):
    listings = [
        make_listing(id=i, title=f"Byt {i}", price=90_000 + i * 1_000, area=54 + i)
        for i in range(6)
    ]
    annotate_segments(listings)  # all "unknown" — no new-segment comps
    out = tmp_path / "cma_fb.html"
    render_report(
        listings,
        query="byt",
        location="MI",
        sources=["bazos.sk"],
        out_path=out,
        mode="cma",
        cma_target_area=55,
        cma_segment="new",
    )
    text = out.read_text(encoding="utf-8")
    assert "using all segments instead" in text
    assert "Recommended range" in text


def test_report_stats_dedupe_cross_posts(tmp_path, make_listing):
    flat = dict(title="MASARYKOVÁ - Priestranný 2 izbový byt", price=108_990, area=59.0)
    listings = [
        make_listing(id=1, source="bazos", **flat),
        make_listing(id=None, source="nehnutelnosti", **flat),
        make_listing(id=None, source="topreality", **flat),
        make_listing(id=4, title="iný byt A", price=90_000, area=50),
        make_listing(id=5, title="iný byt B", price=100_000, area=52),
    ]
    annotate_segments(listings)
    out = tmp_path / "dedup.html"
    render_report(
        listings,
        query="byt",
        location="MI",
        sources=["bazos.sk", "nehnutelnosti.sk", "topreality.sk"],
        out_path=out,
    )
    text = out.read_text(encoding="utf-8")
    assert "5 listings (3 unique" in text  # header shows both counts
    assert "3 listings · 3 priced · 3 with €/m²" in text  # stats on the unique pool


def test_report_cma_comps_dedupe_cross_posts(tmp_path, make_listing):
    flat = dict(title="MASARYKOVÁ - Priestranný 2 izbový byt", price=108_990, area=55.0)
    listings = [
        make_listing(id=1, source="bazos", **flat),
        make_listing(id=None, source="nehnutelnosti", **flat),
        make_listing(id=4, title="iný byt A", price=90_000, area=50),
        make_listing(id=5, title="iný byt B", price=100_000, area=52),
        make_listing(id=6, title="iný byt C", price=110_000, area=57),
    ]
    annotate_segments(listings)
    out = tmp_path / "dedup_cma.html"
    render_report(
        listings,
        query="byt",
        location="MI",
        sources=["bazos.sk", "nehnutelnosti.sk"],
        out_path=out,
        mode="cma",
        cma_target_area=55,
    )
    comps = out.read_text(encoding="utf-8").split("Top comparables")[1].split("</table>")[0]
    assert comps.count("MASARYKOVÁ") == 1  # the cross-posted flat is one comp, not two


def test_render_report_cma_custom_band(tmp_path, make_listing):
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
        cma_area_band=0.10,
    )
    assert "±10%" in out.read_text(encoding="utf-8")
