# # Soft-delete the housing search
# with
#   user_id := <uuid>$user_id,
#   provider := <str>$provider,
#   url := <str>$search_url,

# update HousingSearch
# filter
#   .user.id = user_id
#   and .provider = provider
#   and .url = url
# set {
#   deleted_at := datetime_current(),
# };

# Hard-delete the housing search
with
  user_id := <uuid>$user_id,
  provider := <str>$provider,
  url := <str>$search_url,

delete HousingSearch
filter
  .user.id = user_id
  and .provider = provider
  and .url = url;
