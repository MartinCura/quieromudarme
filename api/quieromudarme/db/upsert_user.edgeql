with
  telegram_id := <int64>$telegram_id,
  telegram_username := <optional str>$telegram_username,

  user := (
    insert User {
      telegram_id := telegram_id,
      telegram_username := telegram_username,
    }
    unless conflict on .telegram_id
    else (
      update User set {
        telegram_username := telegram_username
      }
    )
  )

select user {
  is_new := (user not in User),
  id,
  tier,
  telegram_id,
  telegram_username,
  searches: {
    id,
    created_at,
    provider,
    url,
  } order by .created_at asc,
}
