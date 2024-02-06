select User {
  id,
  tier,
  telegram_id,
  telegram_username,
  num_searches := count(.searches),
}
