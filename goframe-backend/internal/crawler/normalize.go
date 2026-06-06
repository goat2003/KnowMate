package crawler

import (
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"net"
	"net/url"
	"sort"
	"strconv"
	"strings"
)

var ErrInvalidURL = errors.New("invalid_url")

func NormalizeURL(raw string) (string, error) {
	parsed, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return "", fmt.Errorf("%w: %v", ErrInvalidURL, err)
	}

	parsed.Scheme = strings.ToLower(parsed.Scheme)
	if !parsed.IsAbs() || (parsed.Scheme != "http" && parsed.Scheme != "https") || parsed.Host == "" {
		return "", fmt.Errorf("%w: only absolute http and https URLs are supported", ErrInvalidURL)
	}

	hostname := strings.ToLower(parsed.Hostname())
	if hostname == "" {
		return "", fmt.Errorf("%w: host is required", ErrInvalidURL)
	}
	port := parsed.Port()
	if strings.HasSuffix(parsed.Host, ":") {
		return "", fmt.Errorf("%w: port is required after colon", ErrInvalidURL)
	}
	if port != "" {
		portNumber, portErr := strconv.ParseUint(port, 10, 16)
		if portErr != nil {
			return "", fmt.Errorf("%w: invalid port %q", ErrInvalidURL, port)
		}
		if (parsed.Scheme == "http" && portNumber == 80) || (parsed.Scheme == "https" && portNumber == 443) {
			port = ""
		}
	}
	switch {
	case port != "":
		parsed.Host = net.JoinHostPort(hostname, port)
	case strings.Contains(hostname, ":"):
		parsed.Host = "[" + hostname + "]"
	default:
		parsed.Host = hostname
	}

	escapedPath := parsed.EscapedPath()
	if escapedPath == "" {
		escapedPath = "/"
	}
	cleanPath := removeDotSegments(escapedPath)
	decodedPath, err := url.PathUnescape(cleanPath)
	if err != nil {
		return "", fmt.Errorf("%w: invalid path: %v", ErrInvalidURL, err)
	}
	parsed.Path = decodedPath
	parsed.RawPath = cleanPath

	query, err := url.ParseQuery(parsed.RawQuery)
	if err != nil {
		return "", fmt.Errorf("%w: invalid query: %v", ErrInvalidURL, err)
	}
	for key, values := range query {
		lowerKey := strings.ToLower(key)
		if strings.HasPrefix(lowerKey, "utm_") || lowerKey == "fbclid" || lowerKey == "gclid" {
			query.Del(key)
			continue
		}
		sort.Strings(values)
		query[key] = values
	}
	parsed.RawQuery = query.Encode()
	parsed.ForceQuery = false
	parsed.Fragment = ""
	parsed.RawFragment = ""

	return parsed.String(), nil
}

func removeDotSegments(escapedPath string) string {
	segments := strings.Split(strings.TrimPrefix(escapedPath, "/"), "/")
	output := make([]string, 0, len(segments))

	for index, segment := range segments {
		last := index == len(segments)-1
		decodedSegment, err := url.PathUnescape(segment)
		if err != nil {
			decodedSegment = segment
		}
		switch decodedSegment {
		case ".":
			if last {
				output = append(output, "")
			}
		case "..":
			if len(output) > 0 {
				output = output[:len(output)-1]
			}
			if last {
				output = append(output, "")
			}
		default:
			output = append(output, segment)
		}
	}

	return "/" + strings.Join(output, "/")
}

func NormalizeTitle(raw string) string {
	return strings.ToLower(strings.Join(strings.Fields(raw), " "))
}

func SHA256Hex(raw string) string {
	sum := sha256.Sum256([]byte(raw))
	return hex.EncodeToString(sum[:])
}

func StableArticleID(entry RawEntry, normalizedURL, titleHash, contentHash string) string {
	var identity string
	externalID := strings.TrimSpace(entry.ExternalID)
	sourceType := strings.TrimSpace(string(entry.SourceType))
	sourceName := strings.TrimSpace(entry.SourceName)
	normalizedURL = strings.TrimSpace(normalizedURL)
	titleHash = strings.TrimSpace(titleHash)
	contentHash = strings.TrimSpace(contentHash)

	switch {
	case externalID != "" && sourceType != "" && sourceName != "":
		identity = strings.Join([]string{"external", sourceType, sourceName, externalID}, "\x00")
	case normalizedURL != "":
		identity = "url\x00" + normalizedURL
	case titleHash != "" || contentHash != "":
		identity = strings.Join([]string{"hashes", titleHash, contentHash}, "\x00")
	default:
		return ""
	}
	return "article-" + SHA256Hex(identity)
}
