package crawler

import "unicode"

const (
	minLanguageCharacters = 10
	mixedLanguageRatio    = 0.10
)

func DetectLanguage(text string) string {
	var chinese, english int
	for _, r := range text {
		switch {
		case unicode.Is(unicode.Han, r):
			chinese++
		case r >= 'A' && r <= 'Z', r >= 'a' && r <= 'z':
			english++
		}
	}

	total := chinese + english
	if total < minLanguageCharacters {
		return "unknown"
	}

	chineseRatio := float64(chinese) / float64(total)
	englishRatio := float64(english) / float64(total)
	if chineseRatio >= mixedLanguageRatio && englishRatio >= mixedLanguageRatio {
		return "mixed"
	}
	if chinese > english {
		return "zh"
	}
	if english > chinese {
		return "en"
	}
	return "unknown"
}
