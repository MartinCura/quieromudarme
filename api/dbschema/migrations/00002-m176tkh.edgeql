CREATE MIGRATION m176tkhjtzjmbptjlxha6okby7sxmrxsxkt7y7v4n75mvbke7jjhja
    ONTO m1gyexr2lh7y75is7s33s6zufcwxrnpoiwmc2uv4udtltvmvfld4bq
{
  ALTER SCALAR TYPE default::Currency EXTENDING enum<ARS, USD, EUR>;
  ALTER SCALAR TYPE default::Provider {
      DROP CONSTRAINT std::one_of('ZonaProp', 'MercadoLibre');
  };
  ALTER SCALAR TYPE default::Provider {
      CREATE CONSTRAINT std::one_of('ZonaProp', 'MercadoLibre', 'Airbnb');
  };
};
