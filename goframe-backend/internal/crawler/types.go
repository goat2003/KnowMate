package crawler

type SourceType string

const (
	SourceTypeFeed              SourceType = "feed"
	SourceTypeArxiv             SourceType = "arxiv"
	SourceTypeGitHubRelease     SourceType = "github_release"
	SourceTypeHuggingFacePapers SourceType = "huggingface_papers"
	SourceTypeMock              SourceType = "mock"
)

type Source struct {
	Name     string
	Type     SourceType
	URL      string
	Enabled  bool
	MaxItems int
}

type RawEntry struct {
	SourceName       string
	SourceType       SourceType
	ExternalID       string
	URL              string
	Title            string
	RawSourceContent string
	SourceContent    string
	Author           string
	PublishedAt      string
	Tags             []string
	RawPayload       any
}

type ErrorType string

type CrawlError struct {
	Type       ErrorType
	Message    string
	HTTPStatus int
	Retryable  bool
	Err        error
}

func (e *CrawlError) Error() string {
	if e == nil {
		return ""
	}
	if e.Message == "" {
		if e.Err != nil {
			return e.Err.Error()
		}
		return string(e.Type)
	}
	if e.Err == nil {
		return e.Message
	}
	return e.Message + ": " + e.Err.Error()
}

func (e *CrawlError) Unwrap() error {
	if e == nil {
		return nil
	}
	return e.Err
}
