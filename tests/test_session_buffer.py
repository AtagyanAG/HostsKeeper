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
