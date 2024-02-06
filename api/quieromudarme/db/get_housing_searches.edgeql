select HousingSearch {
  user: {
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
order by
  # Premium before Free
  .user.tier desc;
