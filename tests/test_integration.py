import re
import shutil
from pathlib import Path

from pytest import fixture

from epub_read_more_easily import Args, emphasize_file_content


@fixture
def sample_input() -> Path:
    return Path(__file__).parent / "sample_input.html"


@fixture
def sample_expected_output() -> Path:
    return Path(__file__).parent / "sample_expected_output.html"


def _remove_whitespace(s: str | Path) -> str:
    """Remove leading and trailing whitespace in each line and empty lines."""
    if isinstance(s, Path):
        s = s.read_text()
    return "\n".join([line.strip() for line in s.splitlines() if len(line.strip()) > 0])


def test_input_file(sample_input: Path, sample_expected_output: Path, tmp_path: Path) -> None:
    tmp = tmp_path / "output.html"
    args = Args(
        input_path=sample_input,
        inplace=False,
        output_path=tmp,
    )
    assert not tmp.exists()
    emphasize_file_content(args)
    assert tmp.exists()

    # assert that the generated output in tmp is the same as the expected output, but ignore leading and trailing whitespace
    assert _remove_whitespace(tmp) == _remove_whitespace(sample_expected_output)


def test_inplace(sample_input: Path, sample_expected_output: Path, tmp_path: Path) -> None:
    tmp = tmp_path / "in_and_out.html"
    shutil.copy(sample_input, tmp)
    args = Args(
        input_path=tmp,
        inplace=True,
        output_path=None,
    )
    assert tmp.exists()
    emphasize_file_content(args)
    assert tmp.exists()

    assert _remove_whitespace(tmp) == _remove_whitespace(sample_expected_output)
