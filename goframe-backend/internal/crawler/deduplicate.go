package crawler

import "knowledge-post-agent/goframe-backend/internal/model"

func Deduplicate(articles []model.Article, maxItems int) []model.Article {
	seenURLs := make(map[string]struct{})
	seenTitles := make(map[string]struct{})
	seenContent := make(map[string]struct{})
	seenIDs := make(map[string]struct{})
	result := make([]model.Article, 0, len(articles))

	for _, article := range articles {
		if seenNonEmpty(seenURLs, article.URLHash) ||
			seenNonEmpty(seenTitles, article.TitleHash) ||
			seenNonEmpty(seenContent, article.ContentHash) ||
			seenNonEmpty(seenIDs, article.ID) {
			continue
		}
		markNonEmpty(seenURLs, article.URLHash)
		markNonEmpty(seenTitles, article.TitleHash)
		markNonEmpty(seenContent, article.ContentHash)
		markNonEmpty(seenIDs, article.ID)
		result = append(result, article)
		if maxItems > 0 && len(result) >= maxItems {
			break
		}
	}
	return result
}

func Processable(articles []model.Article) []model.Article {
	result := make([]model.Article, 0, len(articles))
	for _, article := range articles {
		if (article.FetchStatus == "success" || article.FetchStatus == "partial") && article.Content != "" {
			result = append(result, article)
		}
	}
	return result
}

func seenNonEmpty(seen map[string]struct{}, key string) bool {
	if key == "" {
		return false
	}
	_, exists := seen[key]
	return exists
}

func markNonEmpty(seen map[string]struct{}, key string) {
	if key != "" {
		seen[key] = struct{}{}
	}
}
