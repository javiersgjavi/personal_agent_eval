from personal_agent_eval import __version__, build_parser


def test_package_import_exposes_version() -> None:
    assert __version__ == "0.1.0"


def test_root_parser_is_named_for_public_cli() -> None:
    parser = build_parser()

    assert parser.prog == "pae"
