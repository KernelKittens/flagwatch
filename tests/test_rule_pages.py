from flagwatch.rule_pages import discover_rule_links, extract_readable_text


def test_discovers_only_bounded_same_origin_rule_links():
    html = """
    <nav><a href='/news'>News</a></nav>
    <a href='/rules'>Rules</a>
    <a href='/faq'>FAQ</a>
    <a href='/code-of-conduct'>Code of conduct</a>
    <a href='https://other.example/rules'>Other rules</a>
    """

    assert discover_rule_links("https://ctf.example/", html) == [
        "https://ctf.example/rules",
        "https://ctf.example/faq",
        "https://ctf.example/code-of-conduct",
    ]


def test_extracts_plain_rule_text_without_active_content():
    html = """
    <html><head><style>.hidden {display:none}</style><script>steal()</script></head>
    <body><nav>Menu noise</nav><main><h1>Rules</h1><p>AI assistance is allowed.</p></main>
    <form><input value='secret'></form></body></html>
    """

    text = extract_readable_text(html)

    assert text == "Rules\nAI assistance is allowed."
    assert "steal" not in text
    assert "secret" not in text
