with
  HW := (
    select HousingWatch
    filter .housing_revision != .housing.current
  ),
  groups := (
    group HW {
      id,
      user: {
        id,
        tier,
        telegram_id,
        telegram_username,
        created_at,
      },
      search: {
        url,
        created_at,
      },
      housing := .housing_revision.housing {
        provider,
        post_id,
        url,
        post_modified_at,
        title,
        image_url,
        whatsapp_phone_number,
        description := <str>json_get(.raw, 'description'),
      },
      old_revision := .housing_revision {
        id,
        price,
        currency,
      },
      current_revision := .housing_revision.housing.current {
        id,
        price,
        currency,
      },
    }
    by .user
  )

select groups {
  user := .key.user,
  watches := .elements {
    id,
    search,
    housing := (
      # TODO: these `limit 1` should be unnecessary but modelling is imperfect
      select .housing limit 1
    ),
    old_revision,
    current_revision := (
      select .current_revision limit 1
    ),
  },
}
order by
  .key.user.tier desc
  then .key.user.created_at asc
;
