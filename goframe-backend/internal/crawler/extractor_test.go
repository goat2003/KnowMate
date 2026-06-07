package crawler

import (
	"errors"
	"os"
	"strconv"
	"strings"
	"testing"

	nethtml "golang.org/x/net/html"
	"golang.org/x/net/html/atom"
)

func TestExtractDocumentPrefersArticleAndExtractsPageMetadata(t *testing.T) {
	raw := readExtractorFixture(t, "article_zh.html")

	got, err := ExtractDocument(raw, "https://example.com/posts/html-extraction")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}

	if got.Title != "理解 HTML 清洗 & 正文提取" {
		t.Fatalf("Title = %q, want Open Graph title", got.Title)
	}
	if got.Author != "张三" {
		t.Fatalf("Author = %q, want %q", got.Author, "张三")
	}
	if got.PublishedAt != "2026-05-20T09:30:00+08:00" {
		t.Fatalf("PublishedAt = %q, want article:published_time", got.PublishedAt)
	}

	for _, want := range []string{
		"网页正文提取需要识别真正承载信息的区域",
		"优先使用 article\n其次使用 main",
		"score = textLength - linkTextLength",
		"最终文本应解码 entity",
	} {
		if !strings.Contains(got.CleanText, want) {
			t.Errorf("CleanText missing %q:\n%s", want, got.CleanText)
		}
	}
	for _, noise := range []string{"站点标题和登录入口", "侧栏推荐", "隐藏节点", "ARIA 隐藏", "样式隐藏", "脚本噪声", "版权"} {
		if strings.Contains(got.CleanText, noise) {
			t.Errorf("CleanText contains noise %q:\n%s", noise, got.CleanText)
		}
	}
}

func TestExtractDocumentPrefersMainAndUsesJSONLDMetadataFallbacks(t *testing.T) {
	raw := readExtractorFixture(t, "article_en.html")

	got, err := ExtractDocument(raw, "https://example.com/articles/reliable-extraction")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}

	if got.Title != "Reliable Content Extraction from JSON-LD" {
		t.Fatalf("Title = %q, want JSON-LD headline", got.Title)
	}
	if got.Author != "Ada Example, Lin Example" {
		t.Fatalf("Author = %q, want JSON-LD authors", got.Author)
	}
	if got.PublishedAt != "2026-04-18T12:00:00Z" {
		t.Fatalf("PublishedAt = %q, want JSON-LD datePublished", got.PublishedAt)
	}
	if !strings.Contains(got.CleanText, "research & development") {
		t.Fatalf("CleanText did not decode entity:\n%s", got.CleanText)
	}
	for _, noise := range []string{"navigation label", "sidebar contains", "Enable scripts", "Embedded unrelated"} {
		if strings.Contains(got.CleanText, noise) {
			t.Errorf("CleanText contains noise %q:\n%s", noise, got.CleanText)
		}
	}
}

func TestExtractDocumentSkipsShortArticleForValidMain(t *testing.T) {
	raw := []byte(`<!doctype html><html><body>
		<article><p>Short teaser.</p></article>
		<main>
			<h1>Complete main story</h1>
			<p>This main story contains enough meaningful prose to be a valid extraction candidate after the short article teaser is rejected.</p>
			<p>The second paragraph confirms that main remains preferred over fallback candidates once it reaches the minimum useful text threshold.</p>
		</main>
	</body></html>`)

	got, err := ExtractDocument(raw, "https://example.com/short-article-main")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}
	if !strings.Contains(got.CleanText, "Complete main story") {
		t.Fatalf("CleanText did not select valid main:\n%s", got.CleanText)
	}
	if strings.Contains(got.CleanText, "Short teaser") {
		t.Fatalf("CleanText retained rejected short article:\n%s", got.CleanText)
	}
}

func TestExtractDocumentSkipsShortArticleForValidFallback(t *testing.T) {
	raw := []byte(`<!doctype html><html><body>
		<article><p>Short teaser.</p></article>
		<section id="complete-story">
			<h1>Complete fallback story</h1>
			<p>This fallback story contains enough meaningful prose to remain extractable when the only article element is an invalid teaser.</p>
			<p>The selected fallback must include this second paragraph and exclude the short article.</p>
		</section>
	</body></html>`)

	got, err := ExtractDocument(raw, "https://example.com/short-article-fallback")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}
	if !strings.Contains(got.CleanText, "Complete fallback story") {
		t.Fatalf("CleanText did not select valid fallback:\n%s", got.CleanText)
	}
	if strings.Contains(got.CleanText, "Short teaser") {
		t.Fatalf("CleanText retained rejected short article:\n%s", got.CleanText)
	}
}

func TestExtractDocumentSkipsLinkOnlyArticleForValidMain(t *testing.T) {
	raw := []byte(`<!doctype html><html><body>
		<article>
			<a href="/one">A long linked teaser that contains no independent article prose and must not count as valid body text.</a>
			<a href="/two">Another long linked teaser exists only to push the visible text above the minimum threshold.</a>
		</article>
		<main>
			<h1>Independent main story</h1>
			<p>This main story contains enough independent prose to be selected after the link-only article candidate is rejected.</p>
			<p>Candidate validity must be based on useful non-link body text rather than total visible text.</p>
		</main>
	</body></html>`)

	got, err := ExtractDocument(raw, "https://example.com/link-only-article")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}
	if !strings.Contains(got.CleanText, "Independent main story") {
		t.Fatalf("CleanText did not select valid main:\n%s", got.CleanText)
	}
	if strings.Contains(got.CleanText, "long linked teaser") {
		t.Fatalf("CleanText retained rejected link-only article:\n%s", got.CleanText)
	}
}

func TestExtractDocumentFallbackUsesTextMinusLinkTextAndSkipsSidebar(t *testing.T) {
	raw := []byte(`<!doctype html><html><head><title>Fallback</title></head><body>
		<div id="menu"><p><a href="/a">Navigation navigation navigation navigation navigation navigation navigation navigation</a></p></div>
		<div class="sidebar"><p>Sidebar recommendations are verbose enough to look plausible, but sidebar containers must be excluded from fallback selection.</p></div>
		<section id="story">
			<h1>Fallback story</h1>
			<p>This is the actual story body with enough independent prose to make its useful text score larger than linked navigation text.</p>
			<p>A second paragraph makes the selected container unambiguous and verifies that paragraph boundaries remain readable.</p>
		</section>
	</body></html>`)

	got, err := ExtractDocument(raw, "https://example.com/fallback")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}
	if !strings.Contains(got.CleanText, "This is the actual story body") {
		t.Fatalf("CleanText did not select story:\n%s", got.CleanText)
	}
	if strings.Contains(got.CleanText, "Navigation navigation") || strings.Contains(got.CleanText, "Sidebar recommendations") {
		t.Fatalf("CleanText selected fallback noise:\n%s", got.CleanText)
	}
}

func TestExtractDocumentFallbackPrefersDenseStoryOverLargeLowDensityWrapper(t *testing.T) {
	raw := []byte(`<!doctype html><html><body>
		<div id="large-wrapper">
			<div><p>Wrapper filler one adds absolute text but very little useful density.</p></div>
			<div><p>Wrapper filler two adds absolute text but very little useful density.</p></div>
			<div><p>Wrapper filler three adds absolute text but very little useful density.</p></div>
			<div><p>Wrapper filler four adds absolute text but very little useful density.</p></div>
			<div><p>Wrapper filler five adds absolute text but very little useful density.</p></div>
			<div><p>Wrapper filler six adds absolute text but very little useful density.</p></div>
			<div><p>Wrapper filler seven adds absolute text but very little useful density.</p></div>
			<div><p>Wrapper filler eight adds absolute text but very little useful density.</p></div>
			<section id="dense-story">
				<h1>Dense fallback story</h1>
				<p>This compact story contains concentrated prose that should outrank a much larger wrapper containing many shallow fragments.</p>
				<p>Its useful text is substantial relative to its small node count, making the density decision explainable.</p>
			</section>
		</div>
	</body></html>`)

	got, err := ExtractDocument(raw, "https://example.com/dense-fallback")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}
	if !strings.Contains(got.CleanText, "Dense fallback story") {
		t.Fatalf("CleanText did not select dense story:\n%s", got.CleanText)
	}
	if strings.Contains(got.CleanText, "Wrapper filler") {
		t.Fatalf("CleanText selected large low-density wrapper:\n%s", got.CleanText)
	}
}

func TestExtractDocumentFallbackUsesVisibleBodyWhenNoCandidateContainerExists(t *testing.T) {
	raw := []byte(`<!doctype html><html><body>
		<nav>Navigation must be removed.</nav>
		<p>The first standalone paragraph contains useful article prose and should remain in the extracted document.</p>
		<p>The second standalone paragraph is also part of the body and must not be discarded by fallback selection.</p>
	</body></html>`)

	got, err := ExtractDocument(raw, "https://example.com/plain-body")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}
	for _, want := range []string{"The first standalone paragraph", "The second standalone paragraph"} {
		if !strings.Contains(got.CleanText, want) {
			t.Errorf("CleanText missing %q:\n%s", want, got.CleanText)
		}
	}
	if strings.Contains(got.CleanText, "Navigation must be removed") {
		t.Fatalf("CleanText retained navigation:\n%s", got.CleanText)
	}
}

func TestExtractDocumentJSONLDHeadlineWinsTopLevelName(t *testing.T) {
	raw := []byte(`<!doctype html><html><head>
		<title>HTML title</title>
		<script type="application/ld+json">{
			"@context": "https://schema.org",
			"name": "Site name",
			"@graph": [{
				"@type": "Article",
				"headline": "Graph article headline",
				"author": {"name": "Graph Author"},
				"datePublished": "2026-03-01"
			}]
		}</script>
	</head><body><article>
		<p>This article contains enough meaningful prose to verify that metadata is extracted from a JSON-LD graph.</p>
		<p>The graph headline must take precedence over the top-level web site name.</p>
	</article></body></html>`)

	got, err := ExtractDocument(raw, "https://example.com/graph")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}
	if got.Title != "Graph article headline" {
		t.Fatalf("Title = %q, want JSON-LD graph headline", got.Title)
	}
}

func TestExtractDocumentIgnoresJSONLDNameAsArticleTitle(t *testing.T) {
	raw := []byte(`<!doctype html><html><head>
		<title>HTML fallback title</title>
		<script type="application/ld+json">{
			"@context": "https://schema.org",
			"@type": "WebSite",
			"name": "Generic site name"
		}</script>
	</head><body><article>
		<p>This article contains enough meaningful prose to verify that a generic JSON-LD name does not replace the HTML title.</p>
		<p>Only a JSON-LD headline should be treated as an article title by the extractor.</p>
	</article></body></html>`)

	got, err := ExtractDocument(raw, "https://example.com/jsonld-name")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}
	if got.Title != "HTML fallback title" {
		t.Fatalf("Title = %q, want HTML title fallback", got.Title)
	}
}

func TestExtractDocumentDoesNotDecodeEntitiesTwice(t *testing.T) {
	raw := []byte(`<!doctype html><html><head>
		<title>Literal &amp;lt; title</title>
		<meta name="author" content="Author &amp;amp; Editor">
	</head><body><article>
		<p>This valid article intentionally contains the literal encoded value &amp;lt;tag&amp;gt; rather than actual markup.</p>
		<p>The extractor must preserve exactly one decoded entity layer for DOM text and metadata values.</p>
	</article></body></html>`)

	got, err := ExtractDocument(raw, "https://example.com/entities")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}
	if !strings.Contains(got.CleanText, "&lt;tag&gt;") || strings.Contains(got.CleanText, "<tag>") {
		t.Fatalf("CleanText decoded entities twice:\n%s", got.CleanText)
	}
	if got.Title != "Literal &lt; title" {
		t.Fatalf("Title = %q, want one decoded entity layer", got.Title)
	}
	if got.Author != "Author &amp; Editor" {
		t.Fatalf("Author = %q, want one decoded entity layer", got.Author)
	}
}

func TestExtractDocumentRemovesNoiseInsideSelectedContentRoot(t *testing.T) {
	raw := []byte(`<!doctype html><html><body><article>
		<h1>Selected article root</h1>
		<p>This valid article contains enough meaningful prose to ensure the article element is selected as the content root.</p>
		<header>internal header noise</header>
		<nav>internal nav noise</nav>
		<footer>internal footer noise</footer>
		<aside>internal aside noise</aside>
		<noscript>internal noscript noise</noscript>
		<iframe>internal iframe noise</iframe>
		<style>.noise { display: block } internal style noise</style>
		<svg><text>internal svg noise</text></svg>
		<form>internal form noise</form>
		<div hidden>internal hidden noise</div>
		<div aria-hidden="true">internal aria hidden noise</div>
		<div style="display:none">internal display hidden noise</div>
		<template>internal template noise</template>
		<p>This concluding paragraph must remain while every noisy descendant inside the selected article root is removed.</p>
	</article></body></html>`)

	got, err := ExtractDocument(raw, "https://example.com/internal-noise")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}
	if !strings.Contains(got.CleanText, "This concluding paragraph must remain") {
		t.Fatalf("CleanText missing selected article prose:\n%s", got.CleanText)
	}
	for _, noise := range []string{
		"internal header noise", "internal nav noise", "internal footer noise", "internal aside noise",
		"internal noscript noise", "internal iframe noise", "internal style noise", "internal svg noise",
		"internal form noise", "internal hidden noise", "internal aria hidden noise", "internal display hidden noise",
		"internal template noise",
	} {
		if strings.Contains(got.CleanText, noise) {
			t.Errorf("CleanText contains noise %q:\n%s", noise, got.CleanText)
		}
	}
}

func TestExtractDocumentJSONLDUsesFirstArticleEntityDeterministically(t *testing.T) {
	raw := []byte(`<!doctype html><html><head>
		<title>HTML fallback title</title>
		<script type="application/ld+json">{
			"headline": "Unclassified headline",
			"author": {"name": "Unclassified Author"},
			"datePublished": "1999-01-01",
			"@graph": [
				{"@type": "WebSite", "headline": "Site headline", "author": {"name": "Site Author"}, "datePublished": "2000-01-01"},
				{"@type": "Comment", "headline": "Comment headline", "author": {"name": "Comment Author"}, "datePublished": "2001-01-01"},
				{"@type": "TechArticle", "headline": "First article headline", "author": {"name": "First Author"}, "datePublished": "2026-06-01"},
				{"@type": "NewsArticle", "headline": "Second article headline", "author": {"name": "Second Author"}, "datePublished": "2026-06-02"}
			]
		}</script>
	</head><body><article>
		<p>This article contains enough meaningful prose to verify deterministic JSON-LD selection from multiple graph entities.</p>
		<p>The first recognized article entity must supply all JSON-LD article metadata fields.</p>
	</article></body></html>`)

	for iteration := 0; iteration < 20; iteration++ {
		got, err := ExtractDocument(raw, "https://example.com/deterministic-jsonld")
		if err != nil {
			t.Fatalf("iteration %d: ExtractDocument() error = %v", iteration, err)
		}
		if got.Title != "First article headline" || got.Author != "First Author" || got.PublishedAt != "2026-06-01" {
			t.Fatalf("iteration %d: metadata = %#v, want first article entity", iteration, got)
		}
	}
}

func TestExtractDocumentJSONLDAcceptsArticleTypeArraysAndDerivedTypes(t *testing.T) {
	raw := []byte(`<!doctype html><html><head>
		<title>HTML fallback title</title>
		<script type="application/ld+json">{
			"@graph": [{
				"@type": ["CreativeWork", "ScholarlyArticle"],
				"headline": "Scholarly result",
				"author": {"name": "Research Author"},
				"datePublished": "2026-06-03"
			}]
		}</script>
	</head><body><article>
		<p>This article contains enough meaningful prose to verify recognized derived article types supplied in a JSON-LD type array.</p>
		<p>Metadata extraction must support common Schema.org article variants without accepting unrelated objects.</p>
	</article></body></html>`)

	got, err := ExtractDocument(raw, "https://example.com/scholarly")
	if err != nil {
		t.Fatalf("ExtractDocument() error = %v", err)
	}
	if got.Title != "Scholarly result" || got.Author != "Research Author" || got.PublishedAt != "2026-06-03" {
		t.Fatalf("metadata = %#v, want scholarly article metadata", got)
	}
}

func TestExtractDocumentWithOptionsAllowsShortAnnouncements(t *testing.T) {
	raw := []byte(`<!doctype html><html><body><article><p>Service restored at 09:30 UTC.</p></article></body></html>`)

	if _, err := ExtractDocument(raw, "https://example.com/announcement"); err == nil {
		t.Fatal("ExtractDocument() error = nil, want default minimum length rejection")
	}

	got, err := ExtractDocumentWithOptions(raw, "https://example.com/announcement", ExtractOptions{
		MinTextLength: 10,
		MaxCandidates: 8,
	})
	if err != nil {
		t.Fatalf("ExtractDocumentWithOptions() error = %v", err)
	}
	if got.CleanText != "Service restored at 09:30 UTC." {
		t.Fatalf("CleanText = %q, want short announcement", got.CleanText)
	}
}

func TestExtractDocumentWithOptionsKeepsHighestScoringFallbackCandidates(t *testing.T) {
	var raw strings.Builder
	raw.WriteString(`<!doctype html><html><body>`)
	for index := 0; index < 50; index++ {
		raw.WriteString(`<div class="candidate-shell" data-depth="`)
		raw.WriteString(strconv.Itoa(index))
		raw.WriteString(`">`)
	}
	raw.WriteString(`<div id="early-low-density">
		<p>Early low density candidate has enough independent prose to qualify, but many shallow nodes must make its score worse than the later story.</p>`)
	for index := 0; index < 100; index++ {
		raw.WriteString(`<span data-filler="`)
		raw.WriteString(strconv.Itoa(index))
		raw.WriteString(`"></span>`)
	}
	raw.WriteString(`</div>`)
	for index := 0; index < 50; index++ {
		raw.WriteString(`</div>`)
	}
	raw.WriteString(`
		<section id="later-high-quality">
			<h1>Later high quality story</h1>
			<p>This concentrated later story contains substantial independent prose and must replace the earlier low scoring candidate in the bounded top list.</p>
			<p>MaxCandidates limits retained candidates, not traversal order, so a later high quality body remains selectable.</p>
		</section>
	</body></html>`)

	got, err := ExtractDocumentWithOptions([]byte(raw.String()), "https://example.com/bounded", ExtractOptions{
		MinTextLength: 50,
		MaxCandidates: 1,
	})
	if err != nil {
		t.Fatalf("ExtractDocumentWithOptions() error = %v", err)
	}
	if !strings.Contains(got.CleanText, "Later high quality story") {
		t.Fatalf("CleanText did not select later top-scoring story:\n%s", got.CleanText)
	}
	if strings.Contains(got.CleanText, "Early low density candidate") {
		t.Fatalf("CleanText retained earlier low-scoring candidate:\n%s", got.CleanText)
	}
}

func TestExtractDocumentReturnsContentExtractionErrorForMissingOrShortBody(t *testing.T) {
	tests := []string{
		`<!doctype html><html><head><title>Only title</title></head><body><nav>Navigation only</nav></body></html>`,
		`<!doctype html><html><body><article><p>Too short.</p></article></body></html>`,
	}

	for _, raw := range tests {
		_, err := ExtractDocument([]byte(raw), "https://example.com/empty")
		var crawlErr *CrawlError
		if !errors.As(err, &crawlErr) {
			t.Fatalf("ExtractDocument() error = %T %v, want *CrawlError", err, err)
		}
		if crawlErr.Type != ErrorContentExtraction {
			t.Fatalf("CrawlError.Type = %q, want %q", crawlErr.Type, ErrorContentExtraction)
		}
	}
}

func TestCleanHTMLFragmentCleansHTMLAndPlainText(t *testing.T) {
	htmlFragment := `<div>
		<p>Hello &amp; welcome.</p>
		<p>Literal entity: &amp;lt;tag&amp;gt;</p>
		<ul><li>First item</li><li>Second item</li></ul>
		<pre><code>go test ./...</code></pre>
		<span style="opacity: 0.5">visible translucent text</span>
		<span hidden>hidden text</span>
		<span style="display: none !important">hidden important text</span>
		<template>hidden template text</template>
		<script>bad()</script>
	</div>`

	got := CleanHTMLFragment(htmlFragment)
	for _, want := range []string{"Hello & welcome.", "Literal entity: &lt;tag&gt;", "First item\nSecond item", "go test ./...", "visible translucent text"} {
		if !strings.Contains(got, want) {
			t.Errorf("CleanHTMLFragment() missing %q:\n%s", want, got)
		}
	}
	if strings.Contains(got, "Literal entity: <tag>") {
		t.Fatalf("CleanHTMLFragment() decoded entity twice:\n%s", got)
	}
	if strings.Contains(got, "hidden text") || strings.Contains(got, "hidden important text") || strings.Contains(got, "hidden template text") || strings.Contains(got, "bad()") {
		t.Fatalf("CleanHTMLFragment() retained noise:\n%s", got)
	}
	if strings.Contains(got, "\n\n\n") {
		t.Fatalf("CleanHTMLFragment() retained excessive blank lines:\n%q", got)
	}

	plain := CleanHTMLFragment("  plain\t text & entity\n\n\n\nnext line  ")
	if plain != "plain text & entity\n\nnext line" {
		t.Fatalf("CleanHTMLFragment(plain) = %q, want normalized plain text", plain)
	}
}

func TestCleanHTMLFragmentFailsClosedOnParserError(t *testing.T) {
	raw := `<p>visible fallback text</p>
		<div hidden><span>hidden attribute secret</span><div>nested hidden secret</div></div>
		<section aria-hidden="true"><div>aria hidden secret</div></section>
		<div style="display: none"><span>display hidden secret</span></div>
		<div style="visibility:hidden"><span>visibility hidden secret</span></div>
		<div class="sidebar"><section>sidebar secret</section></div>
		<div id="related-posts"><span>related chrome secret</span></div>
		<template><div>template secret</div></template>
		<script><div>script secret</div></script>
		<p>visible after hidden content</p>` + strings.Repeat(`<div>`, 600) + `safe tail text`
	context := &nethtml.Node{Type: nethtml.ElementNode, DataAtom: atom.Div, Data: "div"}
	if _, err := nethtml.ParseFragment(strings.NewReader(raw), context); err == nil {
		t.Fatal("test fixture did not trigger the parser error needed to exercise fail-closed fallback")
	}

	got := CleanHTMLFragment(raw)
	for _, want := range []string{"visible fallback text", "visible after hidden content", "safe tail text"} {
		if !strings.Contains(got, want) {
			t.Errorf("CleanHTMLFragment() missing safe fallback text %q:\n%s", want, got)
		}
	}
	for _, forbidden := range []string{"<", ">", "secret", "hidden attribute", "sidebar", "related chrome", "template", "script"} {
		if strings.Contains(got, forbidden) {
			t.Errorf("CleanHTMLFragment() leaked fallback content %q:\n%s", forbidden, got)
		}
	}
}

func TestCleanHTMLFragmentPreservesPreformattedNewlinesAndIndentation(t *testing.T) {
	raw := `<p>Example:</p><pre><code>func main() {
    if ready {
        run()
    }
}</code></pre>`

	got := CleanHTMLFragment(raw)
	want := "func main() {\n    if ready {\n        run()\n    }\n}"
	if !strings.Contains(got, want) {
		t.Fatalf("CleanHTMLFragment() did not preserve pre/code formatting:\n%s", got)
	}
}

func readExtractorFixture(t *testing.T, name string) []byte {
	t.Helper()

	raw, err := os.ReadFile("testdata/" + name)
	if err != nil {
		t.Fatalf("read fixture %q: %v", name, err)
	}
	return raw
}
