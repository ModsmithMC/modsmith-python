from modsmith.platforms._curseforge import html_to_text


def test_curseforge_changelog_html_becomes_plain_text():
    html = """
    <h3>Current release 4.24</h3>
    <ul>
        <li>
            <a href="https://example.invalid">Fix   the
            search</a> - mezz
        </li>
        <li>Faster &amp; smaller</li>
    </ul>
    <p>Thanks<br>everyone</p>
    """
    assert html_to_text(html) == (
        "Current release 4.24\n\n- Fix the search - mezz\n\n- Faster & smaller\n\n"
        "Thanks\neveryone"
    )


def test_empty_changelog():
    assert html_to_text("") == ""
    assert html_to_text("<p>  </p>") == ""
