CREATE MIGRATION m1gk65rnvgckvgwwdfe6ish4yvqwlmc4nqsjej6f7pgxvfxdvyo55a
    ONTO m176tkhjtzjmbptjlxha6okby7sxmrxsxkt7y7v4n75mvbke7jjhja
{
  ALTER TYPE default::HousingSearch {
      CREATE PROPERTY telegram_username := (.user.telegram_username);
  };
};
