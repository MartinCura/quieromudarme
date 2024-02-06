select HousingSearch {
  created_at
}
filter
  .url = <str>$search_url
  and .provider = <str>$provider
  and .user.id = <uuid>$user_id;
