import pytest

from flatview.cli import params_from_args, parse_args


def test_default_args():
    args = parse_args([])
    assert args.query == ""
    assert args.category == "reality"
    assert args.site == "bazos.sk"
    assert args.source == "bazos"
    assert args.radius == 25
    assert args.strict_location is False
    assert args.zip == ""
    assert args.filter == ""
    assert args.export == ""
    assert args.output_dir == "output"


def test_query_positional():
    args = parse_args(["2 izbový byt"])
    assert args.query == "2 izbový byt"


def test_source_all():
    args = parse_args(["--source", "all"])
    assert args.source == "all"


def test_source_nehnutelnosti():
    args = parse_args(["--source", "nehnutelnosti"])
    assert args.source == "nehnutelnosti"


def test_invalid_source():
    with pytest.raises(SystemExit):
        parse_args(["--source", "invalid"])


def test_site_cz():
    args = parse_args(["--site", "bazos.cz"])
    assert args.site == "bazos.cz"


def test_invalid_site():
    with pytest.raises(SystemExit):
        parse_args(["--site", "bazos.de"])


def test_all_flags():
    args = parse_args(
        [
            "query",
            "--category",
            "auto",
            "--subcategory",
            "predam/byt",
            "--location",
            "Bratislava",
            "--radius",
            "10",
            "--strict-location",
            "--price-from",
            "50000",
            "--price-to",
            "200000",
            "--site",
            "bazos.cz",
            "--source",
            "all",
            "--zip",
            "07101",
            "--filter",
            "rekonštr",
            "--pages",
            "5",
            "--export",
            "csv,xlsx",
            "--output-dir",
            "/tmp/out",
        ]
    )
    assert args.query == "query"
    assert args.category == "auto"
    assert args.subcategory == "predam/byt"
    assert args.location == "Bratislava"
    assert args.radius == 10
    assert args.strict_location is True
    assert args.price_from == 50000
    assert args.price_to == 200000
    assert args.site == "bazos.cz"
    assert args.source == "all"
    assert args.zip == "07101"
    assert args.filter == "rekonštr"
    assert args.pages == 5
    assert args.export == "csv,xlsx"
    assert args.output_dir == "/tmp/out"


def test_source_topreality():
    args = parse_args(["--source", "topreality"])
    assert args.source == "topreality"


def test_pages_zero():
    args = parse_args(["--pages", "0"])
    assert args.pages == 0


# --- Subcommands and legacy shim ---


def test_legacy_shim_maps_to_search():
    args = parse_args(["2 izbový byt", "--source", "all"])
    assert args.command == "search"
    assert args.query == "2 izbový byt"
    assert args.source == "all"


def test_empty_args_default_to_search():
    assert parse_args([]).command == "search"


def test_explicit_search_command():
    args = parse_args(["search", "query", "--location", "Michalovce"])
    assert args.command == "search"
    assert args.query == "query"
    assert args.location == "Michalovce"


def test_params_from_args_mapping():
    args = parse_args(
        [
            "search",
            "byt",
            "--source",
            "all",
            "--zip",
            "07101",
            "--filter",
            "rekonštr",
            "--strict-location",
            "--location",
            "Michalovce",
            "--pages",
            "3",
        ]
    )
    params = params_from_args(args)
    assert params.query == "byt"
    assert params.source == "all"
    assert params.zip_code == "07101"
    assert params.title_filter == "rekonštr"
    assert params.strict_location is True
    assert params.location == "Michalovce"
    assert params.pages == 3
