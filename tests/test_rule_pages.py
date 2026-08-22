from flagwatch.rule_pages import (
    discover_embedded_rule_links,
    discover_rule_links,
    discover_script_links,
    discover_sitemap_rule_links,
    extract_javascript_evidence,
    extract_readable_text,
)


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


def test_extracts_crawler_metadata_from_javascript_shell():
    html = """
    <html><head>
      <title>BrunnerCTF 2026</title>
      <meta name="description" content="A 48 hour online CTF from Aug 21 to Aug 23.">
      <script type="module" src="/assets/app.js"></script>
    </head><body><div id="app"></div></body></html>
    """

    assert extract_readable_text(html) == (
        "BrunnerCTF 2026\nA 48 hour online CTF from Aug 21 to Aug 23."
    )


def test_discovers_bounded_same_origin_rule_links_from_sitemap():
    xml = """
    <urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
      <url><loc>https://ctf.example/news</loc></url>
      <url><loc>https://ctf.example/rules</loc></url>
      <url><loc>https://ctf.example/faq#top</loc></url>
      <url><loc>https://ctf.example/rules</loc></url>
      <url><loc>https://other.example/rules</loc></url>
    </urlset>
    """

    assert discover_sitemap_rule_links("https://ctf.example/", xml) == [
        "https://ctf.example/rules",
        "https://ctf.example/faq",
    ]


def test_discovers_only_bounded_same_origin_script_assets():
    html = """
    <script src="/assets/app.js"></script>
    <script src="https://ctf.example/assets/vendor.mjs"></script>
    <script src="https://cdn.example/tracker.js"></script>
    <script>inline()</script>
    """

    assert discover_script_links("https://ctf.example/", html) == [
        "https://ctf.example/assets/app.js",
        "https://ctf.example/assets/vendor.mjs",
    ]


def test_extracts_only_policy_string_literals_without_executing_javascript():
    source = r'''
    steal(document.cookie);
    const noise = "ordinary event copy";
    const matcher = /"quote-inside-a-javascript-regex/;
    const internals = "function ai(e){return e===null?null:e.value}";
    const policy = "We have a strict no-AI policy for the Danish competition.";
    const detail = 'All challenge work must comply with the Danish no-AI policy.';
    '''

    evidence = extract_javascript_evidence(source)

    assert evidence.splitlines() == [
        "We have a strict no-AI policy for the Danish competition.",
        "All challenge work must comply with the Danish no-AI policy.",
    ]
    assert "cookie" not in evidence
    assert "ordinary event copy" not in evidence


def test_discovers_bounded_explicit_https_rule_links_from_javascript():
    source = r'''
    const matcher = /"quote-inside-a-javascript-regex/;
    const rules = "https://danmark.brunnerctf.dk/rules";
    const faq = "/faq#policy";
    const chat = "https://discord.gg/example";
    const insecure = "http://other.example/rules";
    '''

    assert discover_embedded_rule_links("https://ctf.brunnerne.dk/", source) == [
        "https://danmark.brunnerctf.dk/rules",
        "https://ctf.brunnerne.dk/faq",
    ]
