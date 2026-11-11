# Kako samostalno izgraditi i provjeriti Node ISO

ISO je datoteka od koje se izrađuje instalacijski USB. Ovim postupkom dobivaš novi kandidat za Bitcoin Core Node iz javno objavljenih izvora izdanja v0.1.0-rc.2. Objavljeni RC2 izgrađen je na starijem ISO-u. Njegov potpisani SHA-256 služi provjeri tog preuzimanja. Za novi kandidat usporedi dvije izgradnje iste verzije recepta.

## 1. Pripremi računalo

U praznom virtualnom računalu s Debianom 13 za 64-bitni Intel ili AMD otvori Terminal. Za početak dodijeli mu 4 procesorske jezgre, 8 GB RAM-a i 50 GB slobodnog prostora. Izgradnja uz preuzimanje može trajati nekoliko sati. Za ovaj posao ne trebaju ti Bitcoin wallet, privatni ključ ni lozinka od Vaulta. Virtualno računalo treba dopuštati pokretanje Dockera s administrativnim ovlastima.

Pokreni naredbe redom.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl docker.io git gnupg patch
sudo systemctl start docker
git clone https://github.com/btcpavao/bitcoin-core-node-releases.git
cd bitcoin-core-node-releases
git fetch origin reproducible-builds
git switch --detach FETCH_HEAD
git rev-parse HEAD
```

Zapiši svih 40 znakova iz posljednjeg retka. To je **commit**, točna verzija recepta. Svatko tko ponavlja tvoju izgradnju treba koristiti isti commit. Ako provjeravaš već izrađeni kandidat, podesi verziju na commit iz zapisa o njegovoj izgradnji prije sljedećih koraka.

## 2. Pogledaj sadržaj i izmjene

Neovisnim kanalom potvrdi cijeli otisak Pavaova javnog ključa. GitHub i dokument prenesen s istog GitHuba mogu prikazivati isti zamijenjeni ključ. Očekivani je otisak `787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0`.

```bash
gpg --show-keys --fingerprint btcpavao-pgp.asc
bash rebuild/node source ../node-source
```

Druga naredba provjerava potpis i SHA-256 javnog izvornog paketa, raspakira datoteke te primjenjuje izmjene recepta. Očekuj `SOURCE-COMMIT.txt: OK`, oznaku `OK` kraj imena izvornog paketa i na kraju `Complete` s putanjom. Kod poruke o pogrešnom potpisu ili razlici u SHA-256 zaustavi se i sačuvaj poruku.

| Datoteka ili mapa | Što možeš provjeriti |
| --- | --- |
| `rebuild/inputs.env` | Točne verzije i otiske ulaznih podataka |
| `rebuild/node.patch` | Svaku izmjenu izvora RC2 koju uvodi ovaj recept |
| `../node-source/packages.list` | Popis programa za instalaciju |
| `../node-source/app/` i `../node-source/runtime/` | Kod sučelja, pozadinskih servisa, mreže i dozvola |
| `../node-source/installer/` | Izmjene instalacijskog programa i ekrana za prijavu |
| `rebuild/builder.sh` i `rebuild/finalize-root.sh` | Kako se sastavlja i dovršava sustav |

Sljedeće dvije naredbe prikazuju izmjene između javnih izdanja RC1 i RC2.

```bash
bash rebuild/release-diff > ../node-rc1-do-rc2.diff
less ../node-rc1-do-rc2.diff
```

Ova naredba prvo provjerava oba stvarna izvora. U rezultatu redak s `-` označava uklonjeni sadržaj, a redak s `+` dodani. Tipka `q` izlazi iz prikaza. LLM-u možeš dati javni isječak i pitati ga sljedeće. “Objasni ovu promjenu uz naziv datoteke i retka. Koje podatke program čita, gdje ih zapisuje i koje ovlasti traži? Koji dio iz ovog isječka ne možeš provjeriti?” Zaključke provjeri u izvornim datotekama.

## 3. Izgradi ISO

U terminalu ostani u mapi `bitcoin-core-node-releases`. Odredišna mapa mora biti nova.

```bash
sudo bash rebuild/node build ../node-result
sudo cat ../node-result/SHA256SUMS
```

Build ponovno uzima provjereni izvor. Preuzima točno određene pakete, sastavlja instalacijski program i nakon provjera sprema `bitcoin-core-node-candidate-amd64.iso`. Uz njega dobivaš popise paketa i SHA-256. To je otisak svih bajtova datoteke, ispisan kao 64 heksadekadska znaka.

## 4. Ponovi provjeru na drugom računalu

Druga osoba neka na vlastitom, čistom virtualnom računalu ponovi prvi korak. Nakon preuzimanja repozitorija neka pokrene `git switch --detach` s tvojim punim commitom, potvrdi ga s `git rev-parse HEAD`, pa izvrši iste korake za izgradnju.

Ako su oba ISO-a dostupna na jednom računalu, spremi drugi rezultat u mapu `../node-result-two` i pokreni usporedbu.

```bash
sudo bash rebuild/node compare \
  ../node-result/bitcoin-core-node-candidate-amd64.iso \
  ../node-result-two/bitcoin-core-node-candidate-amd64.iso
```

Poruka `MATCH` znači da se svaki bajt poklapa. Ako dobiješ različite SHA-256 vrijednosti, sačuvaj obje datoteke i zapise. Popisi `filesystem.packages`, `builder.packages`, `iso-files.sha256` i `root-files.sha256.gz` pomažu pronaći gdje nastaje razlika.

Na GitHubu posao **Rebuild and compare Node** pokreće dvije izgradnje na čistim radnicima, a posao **compare** uspoređuje cijele datoteke. Za neovisnu potvrdu izvan GitHuba drugi graditelj može javno navesti svoj commit, datum, veličinu ISO-a i SHA-256 te ih potpisati svojim ključem.

[Izgradnje na GitHubu](https://github.com/btcpavao/bitcoin-core-node-releases/actions/workflows/node-rebuild.yml) · [Izvor i potpisani otisci starog izdanja RC2](https://github.com/btcpavao/bitcoin-core-node-releases/releases/tag/v0.1.0-rc.2)
