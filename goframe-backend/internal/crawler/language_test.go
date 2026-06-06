package crawler

import "testing"

func TestDetectLanguage(t *testing.T) {
	tests := []struct {
		name string
		text string
		want string
	}{
		{
			name: "chinese",
			text: "这是一个中文正文，包含足够多的中文字符用于可靠识别。",
			want: "zh",
		},
		{
			name: "english",
			text: "This is a sufficiently long English article body.",
			want: "en",
		},
		{
			name: "mixed",
			text: "这是中文内容 and this is English content mixed together",
			want: "mixed",
		},
		{
			name: "too short",
			text: "中文a",
			want: "unknown",
		},
		{
			name: "no effective characters",
			text: "12345 !!!",
			want: "unknown",
		},
		{
			name: "other scripts",
			text: "Это достаточно длинный русский текст.",
			want: "unknown",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := DetectLanguage(tt.text); got != tt.want {
				t.Fatalf("DetectLanguage(%q) = %q, want %q", tt.text, got, tt.want)
			}
		})
	}
}
