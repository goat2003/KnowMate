package crawler

import (
	"bytes"
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
	"unicode"
	"unicode/utf8"

	nethtml "golang.org/x/net/html"
	"golang.org/x/net/html/atom"
)

const (
	defaultMinTextLength = 50
	defaultMaxCandidates = 256
	fallbackNodeTextCost = 20
	preStartMarker       = "\x00PRE-START\x00"
	preEndMarker         = "\x00PRE-END\x00"
)

type ExtractedDocument struct {
	CleanText   string
	Title       string
	Author      string
	PublishedAt string
}

type ExtractOptions struct {
	MinTextLength int
	MaxCandidates int
}

func ExtractDocument(rawHTML []byte, pageURL string) (ExtractedDocument, error) {
	return ExtractDocumentWithOptions(rawHTML, pageURL, ExtractOptions{
		MinTextLength: defaultMinTextLength,
		MaxCandidates: defaultMaxCandidates,
	})
}

func ExtractDocumentWithOptions(rawHTML []byte, pageURL string, options ExtractOptions) (ExtractedDocument, error) {
	options = normalizeExtractOptions(options)

	root, err := nethtml.Parse(bytes.NewReader(rawHTML))
	if err != nil {
		return ExtractedDocument{}, NewCrawlError(ErrorParse, "could not parse HTML document", 0, false, err)
	}

	metadata := extractMetadata(root)
	contentRoot := preferredContentRoot(root, options)
	cleanText := ""
	if contentRoot != nil {
		cleanText = renderCleanText(contentRoot)
	}
	if effectiveTextLength(cleanText) < options.MinTextLength {
		return ExtractedDocument{}, NewCrawlError(
			ErrorContentExtraction,
			fmt.Sprintf("extracted content is shorter than %d characters", options.MinTextLength),
			0,
			false,
			nil,
		)
	}

	return ExtractedDocument{
		CleanText:   cleanText,
		Title:       metadata.title(),
		Author:      metadata.author(),
		PublishedAt: metadata.publishedAt(),
	}, nil
}

func normalizeExtractOptions(options ExtractOptions) ExtractOptions {
	if options.MinTextLength <= 0 {
		options.MinTextLength = defaultMinTextLength
	}
	if options.MaxCandidates <= 0 {
		options.MaxCandidates = defaultMaxCandidates
	}
	return options
}

func CleanHTMLFragment(raw string) string {
	context := &nethtml.Node{Type: nethtml.ElementNode, DataAtom: atom.Div, Data: "div"}
	nodes, err := nethtml.ParseFragment(strings.NewReader(raw), context)
	if err != nil {
		return safeTextFallback(raw)
	}

	var text strings.Builder
	for _, node := range nodes {
		appendReadableText(&text, node)
	}
	return normalizeReadableText(text.String())
}

type pageMetadata struct {
	htmlTitle        string
	metaAuthor       string
	openGraphTitle   string
	articlePublished string
	jsonLDHeadline   string
	jsonLDAuthor     string
	jsonLDPublished  string
}

func (m pageMetadata) title() string {
	return firstNonEmpty(m.openGraphTitle, m.jsonLDHeadline, m.htmlTitle)
}

func (m pageMetadata) author() string {
	return firstNonEmpty(m.metaAuthor, m.jsonLDAuthor)
}

func (m pageMetadata) publishedAt() string {
	return firstNonEmpty(m.articlePublished, m.jsonLDPublished)
}

func extractMetadata(root *nethtml.Node) pageMetadata {
	var metadata pageMetadata
	walkNodes(root, func(node *nethtml.Node) {
		if node.Type != nethtml.ElementNode {
			return
		}

		switch node.Data {
		case "title":
			if metadata.htmlTitle == "" {
				metadata.htmlTitle = metadataText(node)
			}
		case "meta":
			content := cleanMetadataValue(attributeValue(node, "content"))
			name := strings.ToLower(strings.TrimSpace(attributeValue(node, "name")))
			property := strings.ToLower(strings.TrimSpace(attributeValue(node, "property")))
			switch {
			case name == "author" && metadata.metaAuthor == "":
				metadata.metaAuthor = content
			case property == "og:title" && metadata.openGraphTitle == "":
				metadata.openGraphTitle = content
			case property == "article:published_time" && metadata.articlePublished == "":
				metadata.articlePublished = content
			}
		case "script":
			if strings.EqualFold(strings.TrimSpace(attributeValue(node, "type")), "application/ld+json") {
				extractJSONLD(metadataText(node), &metadata)
			}
		}
	})
	return metadata
}

func extractJSONLD(raw string, metadata *pageMetadata) {
	var value any
	if err := json.Unmarshal([]byte(raw), &value); err != nil {
		return
	}
	article, ok := firstJSONLDArticle(value)
	if !ok {
		return
	}
	if metadata.jsonLDHeadline == "" {
		metadata.jsonLDHeadline = jsonString(article["headline"])
	}
	if metadata.jsonLDAuthor == "" {
		metadata.jsonLDAuthor = jsonAuthors(article["author"])
	}
	if metadata.jsonLDPublished == "" {
		metadata.jsonLDPublished = jsonString(article["datePublished"])
	}
}

func firstJSONLDArticle(value any) (map[string]any, bool) {
	switch typed := value.(type) {
	case []any:
		for _, item := range typed {
			if article, ok := firstJSONLDArticle(item); ok {
				return article, true
			}
		}
	case map[string]any:
		if isArticleJSONLDType(typed["@type"]) {
			return typed, true
		}
		for _, key := range []string{"@graph", "mainEntity", "itemListElement", "hasPart", "subjectOf"} {
			if child, exists := typed[key]; exists {
				if article, ok := firstJSONLDArticle(child); ok {
					return article, true
				}
			}
		}
	}
	return nil, false
}

func isArticleJSONLDType(value any) bool {
	switch typed := value.(type) {
	case string:
		typeName := typed
		if index := strings.LastIndexAny(typeName, "/#"); index >= 0 {
			typeName = typeName[index+1:]
		}
		typeName = strings.ToLower(strings.TrimSpace(typeName))
		return strings.HasSuffix(typeName, "article") ||
			typeName == "blogposting" ||
			typeName == "liveblogposting"
	case []any:
		for _, item := range typed {
			if isArticleJSONLDType(item) {
				return true
			}
		}
	}
	return false
}

func jsonAuthors(value any) string {
	switch typed := value.(type) {
	case string:
		return cleanMetadataValue(typed)
	case []any:
		authors := make([]string, 0, len(typed))
		for _, item := range typed {
			if author := jsonAuthors(item); author != "" {
				authors = append(authors, author)
			}
		}
		return strings.Join(authors, ", ")
	case map[string]any:
		return jsonString(typed["name"])
	default:
		return ""
	}
}

func jsonString(value any) string {
	text, ok := value.(string)
	if !ok {
		return ""
	}
	return cleanMetadataValue(text)
}

type contentStats struct {
	totalText     int
	paragraphText int
	linkText      int
	elements      int
}

type contentCandidate struct {
	node  *nethtml.Node
	stats contentStats
	score int
}

type contentScan struct {
	bestArticle       *nethtml.Node
	bestArticleLength int
	bestMain          *nethtml.Node
	bestMainLength    int
	body              *nethtml.Node
	bodyStats         contentStats
	candidates        []contentCandidate
}

func preferredContentRoot(root *nethtml.Node, options ExtractOptions) *nethtml.Node {
	scan := contentScan{
		candidates: make([]contentCandidate, 0, options.MaxCandidates),
	}
	collectContentStats(root, false, options, &scan)

	if scan.bestArticle != nil {
		return scan.bestArticle
	}
	if scan.bestMain != nil {
		return scan.bestMain
	}

	var best *nethtml.Node
	bestScore := 0
	for _, candidate := range scan.candidates {
		if usefulTextLength(candidate.stats) < options.MinTextLength {
			continue
		}
		score := fallbackScore(candidate.stats)
		if score > bestScore {
			best = candidate.node
			bestScore = score
		}
	}
	if best != nil {
		return best
	}
	if scan.body != nil && usefulTextLength(scan.bodyStats) >= options.MinTextLength {
		return scan.body
	}
	return nil
}

func collectContentStats(node *nethtml.Node, inLink bool, options ExtractOptions, scan *contentScan) contentStats {
	if shouldSkipNode(node) {
		return contentStats{}
	}
	if node.Type == nethtml.TextNode {
		length := effectiveTextLength(node.Data)
		stats := contentStats{totalText: length}
		if inLink {
			stats.linkText = length
		}
		return stats
	}

	stats := contentStats{}
	if node.Type == nethtml.ElementNode {
		stats.elements = 1
		inLink = inLink || node.Data == "a"
	}
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		childStats := collectContentStats(child, inLink, options, scan)
		stats.totalText += childStats.totalText
		stats.paragraphText += childStats.paragraphText
		stats.linkText += childStats.linkText
		stats.elements += childStats.elements
	}
	if node.Type == nethtml.ElementNode && isParagraphLike(node.Data) {
		stats.paragraphText = stats.totalText
	}
	if node.Type == nethtml.ElementNode && isFallbackCandidate(node.Data) {
		retainTopCandidate(scan, contentCandidate{
			node:  node,
			stats: stats,
			score: fallbackScore(stats),
		}, options)
	}
	if node.Type == nethtml.ElementNode {
		usefulLength := usefulTextLength(stats)
		switch node.Data {
		case "article":
			if usefulLength >= options.MinTextLength && usefulLength > scan.bestArticleLength {
				scan.bestArticle = node
				scan.bestArticleLength = usefulLength
			}
		case "main":
			if usefulLength >= options.MinTextLength && usefulLength > scan.bestMainLength {
				scan.bestMain = node
				scan.bestMainLength = usefulLength
			}
		case "body":
			scan.body = node
			scan.bodyStats = stats
		}
	}
	return stats
}

func retainTopCandidate(scan *contentScan, candidate contentCandidate, options ExtractOptions) {
	if usefulTextLength(candidate.stats) < options.MinTextLength || candidate.score <= 0 {
		return
	}
	if len(scan.candidates) < options.MaxCandidates {
		scan.candidates = append(scan.candidates, candidate)
		return
	}

	lowestIndex := 0
	for index := 1; index < len(scan.candidates); index++ {
		if scan.candidates[index].score < scan.candidates[lowestIndex].score {
			lowestIndex = index
		}
	}
	if candidate.score > scan.candidates[lowestIndex].score {
		scan.candidates[lowestIndex] = candidate
	}
}

func fallbackScore(stats contentStats) int {
	usefulText := usefulTextLength(stats)
	if usefulText <= 0 {
		return 0
	}
	denominator := stats.totalText + stats.elements*fallbackNodeTextCost
	return usefulText * 1000 / denominator
}

func usefulTextLength(stats contentStats) int {
	bodyText := stats.paragraphText
	if bodyText == 0 {
		bodyText = stats.totalText
	}
	usefulText := bodyText - stats.linkText
	if usefulText < 0 {
		return 0
	}
	return usefulText
}

func renderCleanText(root *nethtml.Node) string {
	var text strings.Builder
	appendReadableText(&text, root)
	return normalizeReadableText(text.String())
}

func appendReadableText(output *strings.Builder, node *nethtml.Node) {
	if shouldSkipNode(node) {
		return
	}
	if node.Type == nethtml.TextNode {
		if strings.TrimSpace(node.Data) == "" {
			writeInlineSpace(output)
			return
		}
		output.WriteString(node.Data)
		return
	}

	if node.Type == nethtml.ElementNode && node.Data == "pre" {
		writeBoundary(output, 2)
		output.WriteString(preStartMarker)
		appendPreformattedText(output, node)
		output.WriteString(preEndMarker)
		writeBoundary(output, 2)
		return
	}

	if node.Type == nethtml.ElementNode {
		switch node.Data {
		case "br":
			output.WriteByte('\n')
			return
		case "li":
			writeBoundary(output, 1)
		default:
			if isBlockElement(node.Data) {
				writeBoundary(output, 2)
			}
		}
	}

	for child := node.FirstChild; child != nil; child = child.NextSibling {
		appendReadableText(output, child)
	}

	if node.Type == nethtml.ElementNode {
		switch node.Data {
		case "li":
			writeBoundary(output, 1)
		default:
			if isBlockElement(node.Data) {
				writeBoundary(output, 2)
			}
		}
	}
}

func appendPreformattedText(output *strings.Builder, node *nethtml.Node) {
	for child := node.FirstChild; child != nil; child = child.NextSibling {
		if shouldSkipNode(child) {
			continue
		}
		switch {
		case child.Type == nethtml.TextNode:
			output.WriteString(child.Data)
		case child.Type == nethtml.ElementNode && child.Data == "br":
			output.WriteByte('\n')
		default:
			appendPreformattedText(output, child)
		}
	}
}

func writeInlineSpace(output *strings.Builder) {
	current := output.String()
	if current == "" {
		return
	}
	last, _ := utf8.DecodeLastRuneInString(current)
	if !unicode.IsSpace(last) {
		output.WriteByte(' ')
	}
}

func writeBoundary(output *strings.Builder, count int) {
	current := output.String()
	trailing := 0
	for index := len(current) - 1; index >= 0 && current[index] == '\n'; index-- {
		trailing++
	}
	for trailing < count {
		output.WriteByte('\n')
		trailing++
	}
}

func normalizeReadableText(raw string) string {
	sections := make([]string, 0, 3)
	for {
		start := strings.Index(raw, preStartMarker)
		if start < 0 {
			if normal := normalizeNormalText(raw); normal != "" {
				sections = append(sections, normal)
			}
			break
		}
		if normal := normalizeNormalText(raw[:start]); normal != "" {
			sections = append(sections, normal)
		}
		raw = raw[start+len(preStartMarker):]
		end := strings.Index(raw, preEndMarker)
		if end < 0 {
			if normal := normalizeNormalText(raw); normal != "" {
				sections = append(sections, normal)
			}
			break
		}
		if preformatted := normalizePreformattedText(raw[:end]); preformatted != "" {
			sections = append(sections, preformatted)
		}
		raw = raw[end+len(preEndMarker):]
	}
	return strings.Join(sections, "\n\n")
}

func normalizeNormalText(raw string) string {
	raw = strings.ReplaceAll(raw, "\r\n", "\n")
	raw = strings.ReplaceAll(raw, "\r", "\n")

	var normalized strings.Builder
	previousSpace := false
	for _, r := range raw {
		switch {
		case r == '\n':
			normalized.WriteByte('\n')
			previousSpace = false
		case unicode.IsSpace(r):
			if !previousSpace {
				normalized.WriteByte(' ')
				previousSpace = true
			}
		default:
			normalized.WriteRune(r)
			previousSpace = false
		}
	}

	lines := strings.Split(normalized.String(), "\n")
	cleanLines := make([]string, 0, len(lines))
	previousBlank := true
	for _, line := range lines {
		line = strings.TrimSpace(line)
		if line == "" {
			if !previousBlank {
				cleanLines = append(cleanLines, "")
				previousBlank = true
			}
			continue
		}
		cleanLines = append(cleanLines, line)
		previousBlank = false
	}
	for len(cleanLines) > 0 && cleanLines[len(cleanLines)-1] == "" {
		cleanLines = cleanLines[:len(cleanLines)-1]
	}
	return strings.Join(cleanLines, "\n")
}

func normalizePreformattedText(raw string) string {
	raw = strings.ReplaceAll(raw, "\r\n", "\n")
	raw = strings.ReplaceAll(raw, "\r", "\n")
	lines := strings.Split(raw, "\n")
	for len(lines) > 0 && strings.TrimSpace(lines[0]) == "" {
		lines = lines[1:]
	}
	for len(lines) > 0 && strings.TrimSpace(lines[len(lines)-1]) == "" {
		lines = lines[:len(lines)-1]
	}
	for index := range lines {
		lines[index] = strings.TrimRight(lines[index], " \t")
	}
	return strings.Join(lines, "\n")
}

func safeTextFallback(raw string) string {
	tokenizer := nethtml.NewTokenizer(strings.NewReader(raw))
	var output strings.Builder
	hiddenTag := ""
	hiddenDepth := 0
	for {
		switch tokenType := tokenizer.Next(); tokenType {
		case nethtml.ErrorToken:
			return normalizeReadableText(output.String())
		case nethtml.TextToken:
			if hiddenDepth == 0 {
				output.Write(tokenizer.Text())
			}
		case nethtml.StartTagToken:
			token := tokenizer.Token()
			tag := strings.ToLower(token.Data)
			if hiddenDepth > 0 {
				if tag == hiddenTag {
					hiddenDepth++
				}
				continue
			}
			if shouldSkipToken(token) {
				if !isHTMLVoidElement(tag) {
					hiddenTag = tag
					hiddenDepth = 1
				}
				continue
			}
			if isBlockElement(tag) || tag == "br" || tag == "li" {
				writeBoundary(&output, 1)
			}
		case nethtml.SelfClosingTagToken:
			token := tokenizer.Token()
			tag := strings.ToLower(token.Data)
			if hiddenDepth == 0 && !shouldSkipToken(token) && (isBlockElement(tag) || tag == "br" || tag == "li") {
				writeBoundary(&output, 1)
			}
		case nethtml.EndTagToken:
			token := tokenizer.Token()
			tag := strings.ToLower(token.Data)
			if hiddenDepth > 0 {
				if tag == hiddenTag {
					hiddenDepth--
					if hiddenDepth == 0 {
						hiddenTag = ""
					}
				}
				continue
			}
			if isBlockElement(tag) || tag == "li" {
				writeBoundary(&output, 1)
			}
		}
	}
}

func shouldSkipToken(token nethtml.Token) bool {
	node := &nethtml.Node{
		Type: nethtml.ElementNode,
		Data: strings.ToLower(token.Data),
		Attr: token.Attr,
	}
	return shouldSkipNode(node)
}

func isHTMLVoidElement(tag string) bool {
	switch tag {
	case "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
		"param", "source", "track", "wbr":
		return true
	default:
		return false
	}
}

func metadataText(node *nethtml.Node) string {
	var text strings.Builder
	var walk func(*nethtml.Node)
	walk = func(current *nethtml.Node) {
		if current.Type == nethtml.TextNode {
			text.WriteString(current.Data)
		}
		for child := current.FirstChild; child != nil; child = child.NextSibling {
			walk(child)
		}
	}
	walk(node)
	return cleanMetadataValue(text.String())
}

func cleanMetadataValue(raw string) string {
	return strings.Join(strings.Fields(raw), " ")
}

func walkNodes(root *nethtml.Node, visit func(*nethtml.Node)) {
	visit(root)
	for child := root.FirstChild; child != nil; child = child.NextSibling {
		walkNodes(child, visit)
	}
}

func walkVisibleNodes(root *nethtml.Node, visit func(*nethtml.Node)) {
	if shouldSkipNode(root) {
		return
	}
	visit(root)
	for child := root.FirstChild; child != nil; child = child.NextSibling {
		walkVisibleNodes(child, visit)
	}
}

func shouldSkipNode(node *nethtml.Node) bool {
	if node.Type != nethtml.ElementNode {
		return false
	}
	if isRemovedTag(node.Data) || isHidden(node) {
		return true
	}
	return isCommonChrome(node)
}

func isRemovedTag(tag string) bool {
	switch tag {
	case "script", "style", "noscript", "iframe", "svg", "nav", "footer", "header", "aside", "form", "template":
		return true
	default:
		return false
	}
}

func isHidden(node *nethtml.Node) bool {
	if hasAttribute(node, "hidden") {
		return true
	}
	if strings.EqualFold(strings.TrimSpace(attributeValue(node, "aria-hidden")), "true") {
		return true
	}

	for _, declaration := range strings.Split(strings.ToLower(attributeValue(node, "style")), ";") {
		property, value, ok := strings.Cut(declaration, ":")
		if !ok {
			continue
		}
		property = strings.TrimSpace(property)
		value = strings.TrimSpace(strings.TrimSuffix(strings.TrimSpace(value), "!important"))
		switch property {
		case "display":
			if value == "none" {
				return true
			}
		case "visibility":
			if value == "hidden" || value == "collapse" {
				return true
			}
		case "content-visibility":
			if value == "hidden" {
				return true
			}
		case "opacity":
			if opacity, err := strconv.ParseFloat(value, 64); err == nil && opacity == 0 {
				return true
			}
		}
	}
	return false
}

func isCommonChrome(node *nethtml.Node) bool {
	role := strings.ToLower(strings.TrimSpace(attributeValue(node, "role")))
	switch role {
	case "navigation", "complementary", "banner", "contentinfo":
		return true
	}

	identity := attributeValue(node, "id") + " " + attributeValue(node, "class")
	for _, token := range splitIdentityTokens(identity) {
		switch token {
		case "nav", "navbar", "navigation", "sidebar", "sidenav", "footer", "header", "menu",
			"advert", "advertisement", "ads", "promo", "related", "comments":
			return true
		}
	}
	return false
}

func splitIdentityTokens(raw string) []string {
	return strings.FieldsFunc(strings.ToLower(raw), func(r rune) bool {
		return !unicode.IsLetter(r) && !unicode.IsDigit(r)
	})
}

func attributeValue(node *nethtml.Node, key string) string {
	for _, attribute := range node.Attr {
		if strings.EqualFold(attribute.Key, key) {
			return attribute.Val
		}
	}
	return ""
}

func hasAttribute(node *nethtml.Node, key string) bool {
	for _, attribute := range node.Attr {
		if strings.EqualFold(attribute.Key, key) {
			return true
		}
	}
	return false
}

func isFallbackCandidate(tag string) bool {
	switch tag {
	case "section", "div", "td":
		return true
	default:
		return false
	}
}

func isParagraphLike(tag string) bool {
	switch tag {
	case "p", "li", "pre", "blockquote", "h1", "h2", "h3", "h4", "h5", "h6":
		return true
	default:
		return false
	}
}

func isBlockElement(tag string) bool {
	switch tag {
	case "article", "main", "section", "div", "p", "blockquote",
		"h1", "h2", "h3", "h4", "h5", "h6",
		"ul", "ol", "table", "tr":
		return true
	default:
		return false
	}
}

func effectiveTextLength(text string) int {
	length := 0
	for len(text) > 0 {
		r, size := utf8.DecodeRuneInString(text)
		text = text[size:]
		if !unicode.IsSpace(r) {
			length++
		}
	}
	return length
}
