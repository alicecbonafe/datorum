from pathlib import Path

from datorum import configure_logging, get_logger


def test_logging(tmp_path: Path):
    configure_logging()

    log_file = tmp_path / "logs.txt"
    log_name = "mocked-logger"
    log_msg = "Mocked Message!!!"

    configure_logging(log_file=log_file)
    logger = get_logger(log_name)
    logger.warning(log_msg)
    assert log_file.exists()

    file_content = log_file.read_text(encoding="utf-8")
    assert log_name in file_content
    assert log_msg in file_content
