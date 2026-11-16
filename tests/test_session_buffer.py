from hostskeeper.session.buffer import OutputBuffer


def test_output_buffer_cursor_advances() -> None:
    buf = OutputBuffer()
    assert buf.cursor_end() == "0"
    buf.append("hello ")
    first = buf.read_since(None)
    assert first.data == "hello "
    assert first.cursor == "6"
    buf.append("world")
    second = buf.read_since(first.cursor)
    assert second.data == "world"
    assert second.cursor == "11"


def test_output_buffer_cursor_counts_characters_not_utf8_bytes() -> None:
    buf = OutputBuffer()
    buf.append("é🙂x")

    first = buf.read_since(max_chars=2)
    assert first.data == "é🙂"
    assert first.cursor == "2"

    second = buf.read_since(first.cursor, max_chars=1)
    assert second.data == "x"
    assert second.cursor == "3"
