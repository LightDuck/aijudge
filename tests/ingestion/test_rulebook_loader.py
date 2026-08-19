from aijudge.ingestion.rulebook_loader import chunk_text, load_rulebook_file


def test_short_paragraphs_are_grouped_into_one_chunk():
    text = "Paragraph one.\n\nParagraph two."
    chunks = chunk_text(text, max_chars=800)
    assert chunks == ["Paragraph one.\n\nParagraph two."]


def test_paragraphs_exceeding_max_chars_split_into_separate_chunks():
    text = "A" * 500 + "\n\n" + "B" * 500
    chunks = chunk_text(text, max_chars=800)
    assert len(chunks) == 2
    assert chunks[0] == "A" * 500
    assert chunks[1] == "B" * 500


def test_load_rulebook_file_reads_and_chunks(tmp_path):
    file_path = tmp_path / "rulebook.txt"
    file_path.write_text("Section one.\n\nSection two.", encoding="utf-8")

    chunks = load_rulebook_file(file_path)

    assert chunks == ["Section one.\n\nSection two."]
