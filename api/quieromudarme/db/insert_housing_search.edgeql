with
  user := (select User filter .id = <uuid>$user_id),
  provider := <str>$provider,
  url := <str>$search_url,
  query_payload := <optional json>$query_payload,

  created_search := (
    insert HousingSearch {
      user := user,
      provider := provider,
      url := url,
      query_payload := query_payload,
      last_search_at := <datetime>{},
    }
  ),

select created_search {
  id,
  user: {
    id,
    tier,
    telegram_id,
    telegram_username,
  },
  provider,
  url,
  query_payload,
  last_search_at,
  created_at,
}
