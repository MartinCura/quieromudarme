# Inserts or updates HousingWatches for new/updated Housing, HousingRevision
#
# Param `as_notified`: Whether to mark the new/updated HW as already notified

with
  housing_search_id := <uuid>$housing_search_id,
  housing_ids := <array<uuid>>$housing_ids,
  refreshed_at := <datetime>$refreshed_at,
  as_notified := <optional bool>$as_notified ?? False,

  housing_search := assert_exists((
    update HousingSearch
    filter .id = housing_search_id
    set {
      last_search_at := refreshed_at,
    }
  )),

for housing_id in array_unpack(housing_ids) union (
  with
    housing := assert_exists((
      select Housing
      filter .id = housing_id
    )),
    # Existing HouseWatch for this Housing, either from the same or from a different HousingSearch
    existing_hw := (
      select HousingWatch
      filter .user = housing_search.user
        and .housing = housing
    ),

  select if exists existing_hw then (
    update existing_hw
    set {
      housing_revision := (select if as_notified then housing.current else .housing_revision),
      notified_at := (select if as_notified then datetime_current() else .notified_at),
    }
  ) else (
    insert HousingWatch {
      search := housing_search,
      housing_revision := housing.current,
      notified_at := (select if as_notified then datetime_current() else <datetime>{}),
    }
  )
)
