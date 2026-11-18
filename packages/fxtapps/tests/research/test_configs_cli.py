from fxtapps.research.configs.cli import years_text


def test_years_text():
    assert years_text((2020, 2021, 2022, 2024)) == "2020–2022, 2024"
    assert years_text((2020,)) == "2020"
    assert years_text((None,)) == "all"
    assert years_text(()) == "all"
