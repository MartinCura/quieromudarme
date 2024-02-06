# Upsert Housing, creating/updating HousingRevision if appropriate

with
  input := <json>$housing_posts,

for hp in json_array_unpack(input) union (
  with
    housing := (
      insert Housing {
        provider := <Provider>hp['provider'],
        post_id := <str>hp['post_id'],
        url := <str>hp['url'],
        post_modified_at := <datetime>hp['modified_at'],
        title := <str>hp['title'],
        image_url := <str>json_get(hp, 'main_image_url'),
        whatsapp_phone_number := <str>json_get(hp, 'whatsapp_phone_number'),
        raw := <json>hp,
        revisions := (
          insert HousingRevision {
            price := <decimal>hp['price'],
            currency := <Currency>hp['price_currency'],
          }
        ),
      }
      unless conflict on (.provider, .post_id)
      else (
        update Housing
        set {
          url := <str>hp['url'],
          post_modified_at := <datetime>hp['modified_at'],
          title := <str>hp['title'],
          image_url := <str>json_get(hp, 'main_image_url'),
          whatsapp_phone_number := <str>json_get(hp, 'whatsapp_phone_number'),
          raw := <json>hp,
          revisions += (
            with
              # Revision is only added if price has changed significantly
              add_revision := (
                (<decimal>hp['price'] > 0 and <decimal>hp['price'] <= ((1 - PRICE_OFF_PCT_THRESHOLD) * .current.price))
                or (<decimal>hp['price'] = 0 and .current.price > 0)  # price = 0 => not published
                or (<decimal>hp['price'] > 0 and .current.price = 0)
                or <Currency>hp['price_currency'] != .current.currency
              ),
            select if add_revision
            then (
              insert HousingRevision {
                price := <decimal>hp['price'],
                currency := <Currency>hp['price_currency'],
              }
            ) else ({})
          ),
        }
      )
    ),

  select housing {
    id,
    is_new := (housing not in Housing),
    added_revision := (
      housing in Housing
      and housing.current not in HousingRevision
    ),
    price := housing.current.price,
    currency := housing.current.currency,
  }
)
