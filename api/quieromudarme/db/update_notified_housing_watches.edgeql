# Update each HousingWatch so it points to a certain revision and set notified_at
with
  notified_at := <datetime>$notified_at,
  watch_revisions := <array<tuple<hw_id: uuid, revision_id: uuid>>>$watch_revisions,

for wr in array_unpack(watch_revisions) union (
  update HousingWatch
  filter
    .id = wr.hw_id
  set {
    housing_revision := (
      select HousingRevision filter .id = wr.revision_id
    ),
    notified_at := notified_at,
  }
)
