from awp_mcp_projects.code_chunking import chunk_file


def test_chunk_file_short_file_returns_one_chunk() -> None:
    text = "\n".join(f"line {i}" for i in range(10))
    chunks = chunk_file("a.py", text)
    assert len(chunks) == 1
    assert chunks[0].start_line == 1
    assert chunks[0].end_line == 10


def test_chunk_file_empty_returns_no_chunks() -> None:
    assert chunk_file("a.py", "") == []


def test_chunk_file_splits_long_file_with_overlap() -> None:
    text = "\n".join(f"line {i}" for i in range(200))
    chunks = chunk_file("a.py", text, chunk_lines=80, overlap=10)
    assert len(chunks) > 1
    # consecutive chunks overlap by `overlap` lines
    assert chunks[1].start_line == chunks[0].end_line - 10 + 1
    # every line is covered by at least one chunk
    assert chunks[-1].end_line == 200


def test_chunk_file_preserves_path() -> None:
    chunks = chunk_file("src/foo.py", "x = 1\n")
    assert all(c.path == "src/foo.py" for c in chunks)
