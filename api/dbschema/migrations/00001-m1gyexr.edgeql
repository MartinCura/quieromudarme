CREATE MIGRATION m1gyexr2lh7y75is7s33s6zufcwxrnpoiwmc2uv4udtltvmvfld4bq
    ONTO initial
{
  CREATE ALIAS default::MAX_FREE_SEARCHES := (
      2
  );
  CREATE ALIAS default::PRICE_OFF_PCT_THRESHOLD := (
      <std::decimal>0.05
  );
  CREATE ABSTRACT TYPE default::Timestamped {
      CREATE REQUIRED PROPERTY created_at: std::datetime {
          SET readonly := true;
          CREATE REWRITE
              INSERT 
              USING (std::datetime_of_statement());
      };
      CREATE REQUIRED PROPERTY updated_at: std::datetime {
          CREATE REWRITE
              INSERT 
              USING (std::datetime_of_statement());
          CREATE REWRITE
              UPDATE 
              USING (std::datetime_of_statement());
      };
  };
  CREATE SCALAR TYPE default::Provider EXTENDING std::str {
      CREATE CONSTRAINT std::one_of('ZonaProp', 'MercadoLibre');
  };
  CREATE TYPE default::Housing EXTENDING default::Timestamped {
      CREATE REQUIRED PROPERTY post_id: std::str;
      CREATE REQUIRED PROPERTY provider: default::Provider;
      CREATE CONSTRAINT std::exclusive ON ((.provider, .post_id));
      CREATE PROPERTY image_url: std::str;
      CREATE PROPERTY post_modified_at: std::datetime;
      CREATE PROPERTY raw: std::json;
      CREATE PROPERTY title: std::str;
      CREATE REQUIRED PROPERTY url: std::str;
      CREATE PROPERTY whatsapp_phone_number: std::str;
  };
  CREATE ABSTRACT TYPE default::Immutable {
      CREATE ACCESS POLICY immutability
          DENY UPDATE, DELETE  {
              SET errmessage := 'Cannot mutate the immutable';
          };
      CREATE ACCESS POLICY immutable__default_access
          ALLOW SELECT, INSERT ;
  };
  CREATE SCALAR TYPE default::Currency EXTENDING enum<ARS, USD>;
  CREATE TYPE default::HousingRevision EXTENDING default::Timestamped, default::Immutable {
      CREATE REQUIRED PROPERTY currency: default::Currency;
      CREATE REQUIRED PROPERTY price: std::decimal;
  };
  ALTER TYPE default::Housing {
      CREATE REQUIRED MULTI LINK revisions: default::HousingRevision;
      CREATE REQUIRED LINK current := (SELECT
          .revisions ORDER BY
              .created_at DESC
      LIMIT
          1
      );
  };
  ALTER TYPE default::HousingRevision {
      CREATE REQUIRED LINK housing := (std::assert_exists(.<revisions[IS default::Housing]));
  };
  CREATE TYPE default::HousingSearch EXTENDING default::Timestamped {
      CREATE REQUIRED PROPERTY provider: default::Provider;
      CREATE REQUIRED PROPERTY url: std::str;
      CREATE PROPERTY last_search_at: std::datetime;
      CREATE PROPERTY query_payload: std::json;
  };
  CREATE ABSTRACT TYPE default::Undeletable {
      CREATE ACCESS POLICY cannot_delete
          DENY DELETE  {
              SET errmessage := 'Cannot be deleted';
          };
      CREATE ACCESS POLICY undeletable__default_access
          ALLOW SELECT, UPDATE, INSERT ;
  };
  CREATE SCALAR TYPE default::UserTier EXTENDING enum<Free, Premium>;
  CREATE TYPE default::User EXTENDING default::Timestamped, default::Undeletable {
      CREATE REQUIRED PROPERTY telegram_id: std::int64 {
          CREATE CONSTRAINT std::exclusive;
      };
      CREATE PROPERTY telegram_username: std::str {
          CREATE CONSTRAINT std::exclusive;
      };
      CREATE REQUIRED PROPERTY tier: default::UserTier {
          SET default := (default::UserTier.Free);
      };
  };
  ALTER TYPE default::HousingSearch {
      CREATE REQUIRED LINK user: default::User;
      CREATE CONSTRAINT std::exclusive ON ((.user, .provider, .url));
  };
  CREATE TYPE default::HousingWatch EXTENDING default::Timestamped {
      CREATE REQUIRED LINK housing_revision: default::HousingRevision;
      CREATE REQUIRED LINK housing := (.housing_revision.housing);
      CREATE REQUIRED LINK search: default::HousingSearch {
          ON TARGET DELETE DELETE SOURCE;
      };
      CREATE REQUIRED LINK user := (.search.user);
      CREATE TRIGGER exclusive_housing_for_user
          AFTER UPDATE, INSERT 
          FOR ALL DO (std::assert(NOT (EXISTS ((SELECT
              default::HousingWatch
          FILTER
              (((.housing = __new__.housing) AND (.user = __new__.user)) AND (.id != __new__.id))
          ))), message := 'User is already watching this housing'));
      CREATE ANNOTATION std::description := "A housing revision as watched by a user's search";
      CREATE PROPERTY notified_at: std::datetime;
      CREATE REQUIRED PROPERTY notified := ((.notified_at ?!= <std::datetime>{}));
      CREATE INDEX ON (.notified) {
          CREATE ANNOTATION std::description := 'Indexing notified or not.';
      };
  };
  ALTER TYPE default::HousingRevision {
      CREATE LINK watchers := (.<housing_revision[IS default::HousingWatch]);
  };
  ALTER TYPE default::User {
      CREATE MULTI LINK searches := (.<user[IS default::HousingSearch]);
  };
  ALTER TYPE default::HousingSearch {
      CREATE MULTI LINK watches := (.<search[IS default::HousingWatch]);
  };
};
