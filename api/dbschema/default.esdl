module default {

  alias MAX_FREE_SEARCHES := 2;
  alias PRICE_OFF_PCT_THRESHOLD := <decimal>0.05;

  scalar type Currency extending enum<ARS, USD, EUR>;
  scalar type UserTier extending enum<Free, Premium>;
  # scalar type Provider extending enum<ZonaProp, MercadoLibre, Airbnb, Argenprop>;
  scalar type Provider extending str {
    constraint one_of ('ZonaProp', 'MercadoLibre', 'Airbnb');
  }

  abstract type Timestamped {
    required created_at: datetime {
      rewrite insert using (datetime_of_statement());
      readonly := true;
    }
    required updated_at: datetime {
      rewrite insert, update using (datetime_of_statement());
    }
  }

  abstract type Undeletable {
    access policy undeletable__default_access
      allow select, insert, update;
    access policy cannot_delete
      deny delete {
        errmessage := "Cannot be deleted"
      };
  }

  # TODO: couldn't make this work properly and elegantly
  # abstract type SoftDeletable {
  #   deleted_at: datetime;

  #   required deleted := (.deleted_at ?!= <datetime>{});

  #   access policy softdeletable__default_access
  #     allow select, insert, update
  #     using (not .deleted) {
  #       errmessage := "Cannot access or write soft-deleted rows"
  #     }
  #   access policy soft_delete
  #     allow update write
  #     using (.deleted);
  #   access policy hard_delete
  #     deny delete {
  #       errmessage := "Cannot hard delete"
  #     };
  # }

  abstract type Immutable {
    access policy immutable__default_access
      allow select, insert;
    access policy immutability
      deny update, delete {
        errmessage := "Cannot mutate the immutable"
      };
  }


  type User extending Timestamped, Undeletable {
    required tier: UserTier {
      default := UserTier.Free;
    }
    required telegram_id: int64 {
      constraint exclusive;
    }
    telegram_username: str {
      constraint exclusive;
    }

    multi searches := (.<user[is HousingSearch]);
  }

  type HousingSearch extending Timestamped { #, SoftDeletable {
    required user: User;
    required provider: Provider;
    required url: str;
    query_payload: json;
    last_search_at: datetime;

    multi watches := (.<search[is HousingWatch]);
    telegram_username := .user.telegram_username;

    constraint exclusive on ((.user, .provider, .url));
    # TODO: cannot make this work as i want it to
    # access policy max_free_searches
    #   deny insert, update write
    #   using (
    #     .user.tier = UserTier.Free
    #     and count((
    #         select .user.<user[is HousingSearch] filter not .deleted
    #       )) > MAX_FREE_SEARCHES
    #   ) {
    #     errmessage := "You have reached the maximum number of free searches"
    #   };
  }

  type Housing extending Timestamped {
    required provider: Provider;
    required post_id: str;
    required multi revisions: HousingRevision;
    required url: str;
    post_modified_at: datetime;
    title: str;
    image_url: str;
    whatsapp_phone_number: str;
    raw: json;

    required current := (
      select .revisions order by .created_at desc limit 1
    );

    constraint exclusive on ((.provider, .post_id));
  }

  type HousingRevision extending Timestamped, Immutable {
    required price: decimal;
    required currency: Currency;
    # TODO: add expenses, expenses_currency

    # TODO: review how this relationship is modeled
    required housing := assert_exists(.<revisions[is Housing]);
    watchers := (.<housing_revision[is HousingWatch]);
  }

  type HousingWatch extending Timestamped {
    annotation description := "A housing revision as watched by a user's search";

    required housing_revision: HousingRevision;
    required search: HousingSearch {
      on target delete delete source;
    }
    notified_at: datetime;

    required user := .search.user;
    required housing := .housing_revision.housing;
    required notified := (.notified_at ?!= <datetime>{});

    index on (.notified) {
      annotation description := "Indexing notified or not.";
    }
    # access policy default_access
    #   allow all;
    # access policy hide_if_softdeleted_search
    #   deny all
    #   using (.search.deleted) {
    #     errmessage := "Cannot access if its search was soft-deleted"
    #   };
    trigger exclusive_housing_for_user after insert, update for all do (
      assert(
        not exists (
          select HousingWatch
          filter
            .housing = __new__.housing
            and .user = __new__.user
            and .id != __new__.id
        ),
        message := "User is already watching this housing",
      )
    );
  }
}
