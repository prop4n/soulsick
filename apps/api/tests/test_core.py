from soulsick.matching import FileRef, TrackRef, match_files, parse_numbers
from soulsick.naming import TrackNaming, render_path, safe_component, sanitize
from soulsick.quality import FileInfo, detect_format, worst_format
from soulsick.scoring import PeerResult, ReleaseOption, RemoteFile, group_key, rank_candidates

PROFILE = ["flac-24", "flac", "mp3-320", "mp3-v0"]

TRACKS = [
    TrackRef(1, 1, "Smells Like Teen Spirit", 301),
    TrackRef(1, 2, "In Bloom", 254),
    TrackRef(1, 3, "Come as You Are", 219),
]


# --- quality ---------------------------------------------------------------

def test_detect_format():
    assert detect_format(FileInfo("flac", bit_depth=24)) == "flac-24"
    assert detect_format(FileInfo("flac", bit_depth=16)) == "flac"
    assert detect_format(FileInfo("flac")) == "flac"
    assert detect_format(FileInfo("mp3", bitrate=320)) == "mp3-320"
    assert detect_format(FileInfo("mp3", bitrate=245, vbr=True)) == "mp3-v0"
    assert detect_format(FileInfo("mp3", bitrate=128)) == "mp3-low"
    assert detect_format(FileInfo("txt")) is None


def test_worst_format():
    assert worst_format(["flac", "flac-24"], PROFILE) == "flac"
    assert worst_format(["flac", None], PROFILE) is None


# --- naming ----------------------------------------------------------------

def test_render_path_single_disc():
    t = TrackNaming("Nirvana", "Nirvana", "Nevermind", "1991", "In Bloom", 2, 1, 1, "FLAC")
    assert render_path("{albumartist}/{year} - {album}/{disc_prefix}{track:02} - {title}", t) == (
        "Nirvana/1991 - Nevermind/02 - In Bloom.flac"
    )


def test_render_path_multi_disc_and_sanitize():
    t = TrackNaming("AC/DC", "AC/DC", "Live: 1992?", "1992", "T.N.T.", 4, 2, 2, "mp3")
    assert render_path("{albumartist}/{year} - {album}/{disc_prefix}{track:02} - {title}", t) == (
        "AC_DC/1992 - Live_ 1992_/2-04 - T.N.T.mp3"
    )
    assert sanitize("  a  b. ") == "a b"


# --- matching --------------------------------------------------------------

def test_render_path_long_names_fit_the_filesystem():
    """Real case: a "zalgo" title stacks combining marks; the file name went over 255 bytes
    and the filesystem refused it. Every segment fits, on a character boundary, extension kept."""
    title = "M̶̲̺︦̅̄̄͆͞A̵͙︦̿̅̚E̠̠︦̄͆͆V̶̲̲̠︦̿̄E̶̲︦̿̿̅̄͆͟" * 6
    p = render_path(
        "{albumartist}/{year} - {album}/{track:02} - {title}",
        TrackNaming("Ptite Soeur", "Ptite Soeur", title, "2025", title, 8, 1, 1, "flac"),
    )
    parts = p.split("/")
    assert all(len(x.encode()) <= 255 for x in parts), [len(x.encode()) for x in parts]
    assert parts[-1].startswith("08 - M") and parts[-1].endswith(".flac")
    assert parts[1].startswith("2025 - M")
    # Short names are left alone
    assert render_path("{track:02} - {title}", TrackNaming("A", "A", "B", "2020", "Song", 1, 1, 1, "flac")) == "01 - Song.flac"


def test_safe_component_fits_the_filesystem():
    name = "08 " + "Z̶̲̲̠︦̿̿̄̄" * 40 + ".flac"
    out = safe_component(name)
    assert len(out.encode()) <= 255 and out.endswith(".flac") and out.startswith("08 Z")


def test_parse_numbers():
    assert parse_numbers("Music\\Nirvana\\Nevermind\\01 - Smells.flac") == (None, 1)
    assert parse_numbers("x\\CD2\\03 Track.flac") == (2, 3)
    assert parse_numbers("x\\1-04 Track.flac") == (1, 4)
    assert parse_numbers("x\\Track.flac") == (None, None)


def test_match_files_by_title_and_number():
    files = [
        FileRef("a\\03 - Come As You Are.flac", 219),
        FileRef("a\\01 - Nirvana - Smells Like Teen Spirit.flac", 300),
        FileRef("a\\02 - In Bloom.flac", 255),
    ]
    m = match_files(TRACKS, files, artist_hint="Nirvana")
    assert [(a.file_index, a.track_index) for a in m.assignments] == [(1, 0), (2, 1), (0, 2)]
    assert m.unmatched_tracks == []
    assert m.confidence > 0.9


def test_match_files_missing_track():
    files = [FileRef("a\\01 - Smells Like Teen Spirit.mp3"), FileRef("a\\02 - In Bloom.mp3")]
    m = match_files(TRACKS, files)
    assert m.unmatched_tracks == [2]


# --- scoring ---------------------------------------------------------------

def _peer(user, files, slots=True, queue=0, speed=1_000_000):
    return PeerResult(user, slots, speed, queue, files)


def test_group_key_merges_disc_folders():
    assert group_key("M\\Album\\CD1\\01.flac") == "M\\Album"
    assert group_key("M\\Album\\01.flac") == "M\\Album"


def test_rank_candidates_prefers_flac_and_rejects_with_reason():
    rel = ReleaseOption(1, "Nevermind", TRACKS)
    flac = [RemoteFile(f"u\\Nevermind\\0{i+1} - {t.title}.flac", bit_depth=16, duration=int(t.length_s))
            for i, t in enumerate(TRACKS)]
    mp3 = [RemoteFile(f"v\\Nevermind\\0{i+1} - {t.title}.mp3", bitrate=320) for i, t in enumerate(TRACKS)]
    low = [RemoteFile(f"w\\Nevermind\\0{i+1} - {t.title}.mp3", bitrate=128) for i, t in enumerate(TRACKS)]
    partial = flac[:1]
    partial = [RemoteFile(f.filename.replace("u\\", "x\\"), bit_depth=16) for f in partial]

    cands = rank_candidates(
        [_peer("mp3user", mp3), _peer("flacuser", flac), _peer("lowuser", low), _peer("partial", partial)],
        [rel],
        PROFILE,
    )
    by_user = {c.username: c for c in cands}
    assert cands[0].username == "flacuser"
    assert not by_user["mp3user"].rejected
    assert by_user["flacuser"].score > by_user["mp3user"].score
    assert by_user["lowuser"].reject_reason.key == "reject.format_refused"
    assert by_user["partial"].reject_reason.key == "reject.missing_tracks"
    assert "not allowed" in by_user["lowuser"].reject_reason.text
    assert by_user["flacuser"].detail["match"]["tracks_matched"] == 3


def test_editions_identiques_dedoublonnees():
    from soulsick.scoring import compatible, unique_tracklists

    a = ReleaseOption(1, "CD", TRACKS)
    b = ReleaseOption(2, "Vinyle", [TrackRef(t.disc, t.position, t.title.upper(), t.length_s) for t in TRACKS])
    c = ReleaseOption(3, "Deluxe", TRACKS + [TrackRef(1, 4, "Bonus", 100)])
    assert [r.release_id for r in unique_tracklists([a, b, c])] == [1, 3]  # même tracklist → une seule
    big = ReleaseOption(4, "Coffret", [TrackRef(1, i, f"T{i}", 100) for i in range(1, 41)])
    assert [r.release_id for r in compatible([a, big], 3)] == [1]
    assert [r.release_id for r in compatible([big], 3)] == [4]  # rien de compatible : on garde tout


def test_notation_rapide_avec_beaucoup_d_editions():
    """Régression : 150 éditions × 500 dossiers ne doit pas prendre une minute."""
    import time

    editions = [ReleaseOption(i, f"Ed {i}", TRACKS) for i in range(140)] + [
        ReleaseOption(1000 + i, f"Variante {i}", TRACKS + [TrackRef(1, 4, f"Bonus {i}", 120)]) for i in range(10)
    ]
    peers = [
        PeerResult(f"u{p}", True, 1_000_000, 0,
                   [RemoteFile(f"u{p}\\A\\0{i+1} - {t.title}.flac", bit_depth=16, duration=int(t.length_s))
                    for i, t in enumerate(TRACKS)])
        for p in range(500)
    ]
    t0 = time.perf_counter()
    res = rank_candidates(peers, editions, PROFILE)
    assert time.perf_counter() - t0 < 5
    assert not res[0].rejected and res[0].detail["match"]["tracks_matched"] == 3


# --- un fichier d'un autre album ne compte pas pour une piste sur son seul numéro ------


def _release(titles_lengths):
    from soulsick.models import Release, Track
    rel = Release(id=1, mbid="r", release_group_id=1, title="Voir Mauvais", disc_count=1)
    rel.tracks = [
        Track(id=100 + i, release_id=1, mbid=f"t{i}", recording_mbid=f"r{i}", disc=1, position=i + 1,
              title=t, length_ms=ln)
        for i, (t, ln) in enumerate(titles_lengths)
    ]
    return rel


VM = [("machine virtuelle", 112000), ("la chose", 110000), ("100 bouche(s)", 110000),
      ("eugene stoner", 111000), ("warp 0", 111000), ("A7", 138000)]


def test_couverture_refuse_un_titre_sans_rapport_sur_le_seul_numero():
    """Cas réel : « 06-deviantart.flac » (autre EP du même pair) pris pour la piste 06 « A7 »."""
    from soulsick.models import Candidate
    from soulsick.services.coverage import _track_map

    other_ep = Candidate(files=[{"filename": "x\\2026-(vm)vm_[vraiment_moyen]\\06-deviantart.flac", "duration": 110}])
    assert _track_map(other_ep, _release(VM), "Ptite Soeur") == {}

    # Sans titre dans le nom, le numéro reste ce qui compte
    bare = Candidate(files=[{"filename": "x\\VM\\06.flac", "duration": 138}, {"filename": "x\\VM\\05.flac", "duration": 111}])
    assert set(_track_map(bare, _release(VM), "Ptite Soeur")) == {105, 104}


def test_import_prefere_le_bon_titre_a_la_source_la_plus_recente():
    """Cas réel : « 06-deviantart » (source plus récente) avait pris la piste 03 au vrai « 03-100_bouche(s) »."""
    from soulsick.matching import Assignment
    from soulsick.services.importer import pick_key

    right = pick_key("flac-24", failed=False, candidate_id=1328, a=Assignment(0, 2, 0.75, 1.0, True, 0.2))
    wrong = pick_key("flac-24", failed=False, candidate_id=1333, a=Assignment(0, 2, 0.46, 0.52, False, 0.2))
    assert right < wrong
    # À correspondance égale, le meilleur format gagne toujours
    flac24 = pick_key("flac-24", failed=False, candidate_id=1, a=Assignment(0, 2, 0.9, 1.0, True, 0.2))
    flac16 = pick_key("flac", failed=False, candidate_id=2, a=Assignment(0, 2, 0.9, 1.0, True, 0.2))
    assert flac24 < flac16
