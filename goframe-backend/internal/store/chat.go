package store

import "context"

// ChatPreferences supplies canonical conversation preferences to the existing article pipeline.
func (s *Store) ChatPreferences(ctx context.Context, userID string) (map[string]string, error) {
	db, err := s.open(ctx)
	if err != nil {
		return nil, err
	}
	rows, err := db.QueryContext(ctx, `SELECT memory_key,value FROM chat_memories WHERE user_id=?`, userID)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := map[string]string{}
	for rows.Next() {
		var key, value string
		if err = rows.Scan(&key, &value); err != nil {
			return nil, err
		}
		result[key] = value
	}
	return result, rows.Err()
}
