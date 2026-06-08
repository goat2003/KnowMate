package crawler

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

func TestCrawlerIntegrationHandlesFiveSourceTypesAndFailures(t *testing.T) {
	var baseURL string
	server := httptest.NewServer(http.HandlerFunc(func(writer http.ResponseWriter, request *http.Request) {
		switch request.URL.Path {
		case "/robots.txt":
			fmt.Fprint(writer, "User-agent: *\nDisallow: /article/denied\nDisallow: /source/denied\n")
		case "/article/en":
			writer.Header().Set("Content-Type", "text/html")
			fmt.Fprint(writer, integrationArticle("English fixture", "Fixture Author", "This is the primary English article paragraph with enough useful content for extraction and language detection."))
		case "/article/zh":
			writer.Header().Set("Content-Type", "text/html")
			fmt.Fprint(writer, integrationArticle("中文测试文章", "测试作者", "这是用于集成测试的中文正文内容，包含足够多的中文字符用于正文提取和语言识别。正文还会验证作者、发布时间、清洗结果以及内容哈希是否能够稳定生成。"))
		case "/article/denied":
			writer.Header().Set("Content-Type", "text/html")
			fmt.Fprint(writer, integrationArticle("Denied", "", "This page must not be fetched because robots denies it."))
		case "/rss.xml":
			writer.Header().Set("Content-Type", "application/rss+xml")
			fmt.Fprintf(writer, `<?xml version="1.0"?><rss version="2.0"><channel><title>RSS</title><link>%s</link><item><guid>rss-1</guid><title>RSS English</title><link>%s/article/en?utm_source=test</link><description>RSS fallback content for the English article.</description></item></channel></rss>`, baseURL, baseURL)
		case "/atom.xml":
			writer.Header().Set("Content-Type", "application/atom+xml")
			fmt.Fprintf(writer, `<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>Atom</title><id>%s/atom.xml</id><entry><id>atom-1</id><title>Atom Chinese</title><link href="%s/article/zh"/><summary>Atom 中文回退正文。</summary></entry></feed>`, baseURL, baseURL)
		case "/arxiv.xml":
			writer.Header().Set("Content-Type", "application/atom+xml")
			fmt.Fprintf(writer, `<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>arXiv</title><id>%s/arxiv.xml</id><entry><id>arxiv-1</id><title>Arxiv Paper</title><link href="%s/article/en"/><summary>Arxiv fallback abstract.</summary><author><name>Arxiv Author</name></author></entry></feed>`, baseURL, baseURL)
		case "/github.xml":
			writer.Header().Set("Content-Type", "application/atom+xml")
			fmt.Fprintf(writer, `<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><title>GitHub Releases</title><id>%s/github.xml</id><entry><id>release-1</id><title>v1.0.0</title><link href="%s/article/denied"/><content type="html">&lt;p&gt;Release fallback notes.&lt;/p&gt;</content></entry></feed>`, baseURL, baseURL)
		case "/huggingface.xml":
			writer.Header().Set("Content-Type", "application/rss+xml")
			fmt.Fprint(writer, `<?xml version="1.0"?><rss version="2.0"><channel><title>Hugging Face Daily Papers</title><link>https://huggingface.co/papers</link><item><guid>https://huggingface.co/papers/2606.00001</guid><title>HF Paper</title><link>https://huggingface.co/papers/2606.00001</link><description>Hugging Face fallback paper abstract with sufficient content.</description></item></channel></rss>`)
		case "/source/fail":
			http.Error(writer, "temporary source failure", http.StatusServiceUnavailable)
		case "/source/denied":
			writer.Header().Set("Content-Type", "application/rss+xml")
			fmt.Fprintf(writer, `<?xml version="1.0"?><rss version="2.0"><channel><title>Denied</title><link>%s</link><item><guid>denied-source-1</guid><title>Denied source item</title><link>%s/article/en</link></item></channel></rss>`, baseURL, baseURL)
		case "/papers/2606.00001":
			http.NotFound(writer, request)
		default:
			http.NotFound(writer, request)
		}
	}))
	defer server.Close()
	baseURL = server.URL
	localURL, err := url.Parse(baseURL)
	if err != nil {
		t.Fatal(err)
	}

	client := New(Options{
		HTTP: HTTPOptions{
			UserAgent:        "KnowMateCrawler/1.0",
			Timeout:          time.Second,
			RetryTimes:       0,
			PerHostInterval:  0,
			MaxResponseBytes: 1 << 20,
			Transport: integrationRoundTripFunc(func(request *http.Request) (*http.Response, error) {
				if request.URL.Hostname() == "huggingface.co" {
					cloned := request.Clone(request.Context())
					cloned.URL.Scheme = localURL.Scheme
					cloned.URL.Host = localURL.Host
					request = cloned
				}
				return http.DefaultTransport.RoundTrip(request)
			}),
		},
		RobotsCacheTTL: time.Minute,
		SourceMaxItems: 2,
	})

	sources := []Source{
		{Name: "rss", Type: SourceTypeFeed, URL: baseURL + "/rss.xml", Enabled: true},
		{Name: "atom", Type: SourceTypeFeed, URL: baseURL + "/atom.xml", Enabled: true},
		{Name: "arxiv", Type: SourceTypeArxiv, URL: baseURL + "/arxiv.xml", Enabled: true},
		{Name: "github", Type: SourceTypeGitHubRelease, URL: baseURL + "/github.xml", Enabled: true},
		{Name: "huggingface", Type: SourceTypeHuggingFacePapers, URL: baseURL + "/huggingface.xml", Enabled: true},
		{Name: "broken", Type: SourceTypeFeed, URL: baseURL + "/source/fail", Enabled: true},
		{Name: "denied-source", Type: SourceTypeFeed, URL: baseURL + "/source/denied", Enabled: true},
	}

	results := make(map[string]SourceResult, len(sources))
	for _, source := range sources {
		results[source.Name] = client.FetchSource(context.Background(), source)
	}

	for _, name := range []string{"rss", "atom", "arxiv"} {
		result := results[name]
		if result.Status != "success" || len(result.Articles) != 1 {
			t.Fatalf("%s result = %#v", name, result)
		}
		if result.Articles[0].ContentHash == "" || result.Articles[0].NormalizedURL == "" {
			t.Fatalf("%s article fields missing: %#v", name, result.Articles[0])
		}
	}
	for _, name := range []string{"github", "huggingface"} {
		result := results[name]
		if result.Status != "partial" || len(result.Articles) != 1 {
			t.Fatalf("%s result = %#v", name, result)
		}
		if result.Articles[0].Content == "" || result.Articles[0].FetchErrorType == "" {
			t.Fatalf("%s fallback article missing diagnostics: %#v", name, result.Articles[0])
		}
	}
	if result := results["broken"]; result.Status != "failed" || result.ErrorType != string(ErrorHTTP5xx) {
		t.Fatalf("broken source result = %#v", result)
	}
	if result := results["denied-source"]; result.Status != "failed" || result.ErrorType != string(ErrorRobotsDenied) {
		t.Fatalf("denied source result = %#v", result)
	}
	if results["rss"].Status != "success" {
		t.Fatal("failed source affected successful source")
	}
}

func TestCrawlerIntegrationMockSourceDoesNotFetchNetwork(t *testing.T) {
	client := New(Options{HTTP: HTTPOptions{Timeout: 50 * time.Millisecond}, SourceMaxItems: 1})
	result := client.FetchSource(context.Background(), Source{Name: "mock", Type: SourceTypeMock, URL: "mock://sample", Enabled: true})
	if result.Status != "success" || len(result.Articles) != 1 {
		t.Fatalf("mock result = %#v", result)
	}
	if result.Articles[0].FetchError != "" || !strings.HasPrefix(result.Articles[0].ID, "article-") || result.Articles[0].NormalizedURL == "" {
		t.Fatalf("unexpected mock article = %#v", result.Articles[0])
	}
}

func integrationArticle(title, author, body string) string {
	return fmt.Sprintf(`<!doctype html><html><head><title>%s</title><meta name="author" content="%s"></head><body><nav>navigation</nav><article><h1>%s</h1><p>%s</p></article></body></html>`, title, author, title, body)
}

type integrationRoundTripFunc func(*http.Request) (*http.Response, error)

func (function integrationRoundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return function(request)
}
