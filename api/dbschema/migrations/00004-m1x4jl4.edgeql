CREATE MIGRATION m1x4jl4hdanxghvd4446olxvzfss36lgqwvw5pbmg4tmrkbomglfrq
    ONTO m1gk65rnvgckvgwwdfe6ish4yvqwlmc4nqsjej6f7pgxvfxdvyo55a
{
  ALTER SCALAR TYPE default::Provider {
      DROP CONSTRAINT std::one_of('ZonaProp', 'MercadoLibre', 'Airbnb');
  };
  ALTER SCALAR TYPE default::Provider {
      CREATE CONSTRAINT std::one_of('ZonaProp', 'MercadoLibre', 'Airbnb', 'Blueground');
  };
};
