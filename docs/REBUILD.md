# Build and compare a Bitcoin Core Node ISO

[Upute na hrvatskom](REBUILD.hr.md)

This recipe builds a **new candidate** from the public source of v0.1.0-rc.2. The old RC2 image was made from an earlier image and records its hash in BUILD-INFO.json. Its original build did not lock every input. The signed RC2 checksum authenticates that historical download. The comparison below uses two candidates built from the same revision of this recipe.

## 1. Set up a build computer

Use a fresh 64-bit Intel/AMD Debian 13 virtual machine with internet access and a user with sudo access. As an initial allocation, allow 4 CPU cores, 8 GB RAM and 50 GB of free VM disk. Downloading Debian and compiling the installer can take hours. Keep wallets and other personal files outside this VM. The Debian image builder uses a privileged Docker container for mounting filesystems.

Open Terminal in the VM. Run each block in order.

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

Write down the full 40-character value printed by the last command. It identifies the exact revision of the recipe. Share that value with the second builder. On the second machine, use `git switch --detach` followed by that full value after fetching the branch. Git lets you review what changed between two revisions by running `git diff OLDER_COMMIT NEWER_COMMIT -- rebuild`, replacing both names with real commit IDs.

## 2. Verify and inspect the source before building

[Browse the exact RC2 source files](https://github.com/btcpavao/bitcoin-core-node-releases/tree/669e90f9768975924ae443225f23f78cb4a28ecf/source) · [Review the 42 source changes from RC1 to RC2](https://github.com/btcpavao/bitcoin-core-node-releases/compare/5f5770f7000d9d7fa05687279b21bf26e1293a86...669e90f9768975924ae443225f23f78cb4a28ecf)

Confirm the publisher's full OpenPGP fingerprint with Pavao through an independently known channel. The expected primary fingerprint is `787A 2AAF B0D1 19CA 0522 B2A5 B9C9 9AF8 5788 96D0`. View the fingerprint in the local key, then download the source.

```bash
gpg --show-keys --fingerprint btcpavao-pgp.asc
bash rebuild/node source ../node-source
```

The command uses an isolated keyring, checks the signature and the expected signer, checks the archive and source commit against signed SHA-256 entries, then applies the public build patch. Success prints the destination. It needs about 1 MB of compressed project source and does not download the old ISO.

| What to inspect | Where to look |
| --- | --- |
| Exact inputs and build environment | `rebuild/inputs.env`, `rebuild/builder.sh` |
| Each change made to the historical source | `rebuild/node.patch` (lines starting with `+` add code, `-` remove code) |
| Files adjusted just before the system is packed | `rebuild/finalize-root.sh` |
| Software installed and its source checks | `../node-source/packages.list`, `../node-source/build-iso.sh`, `../node-source/provenance/` |
| Desktop, services, permissions, network and installer | `../node-source/app/`, `../node-source/runtime/`, `../node-source/installer/` |

To see each source change from the older RC1 release to RC2, create a patch file. This helper checks each release's own signature and archive checksum before comparing the two extracted trees. The file is ordinary text. Search for a filename, or let an LLM explain a small section and confirm its explanation against the code.

```bash
bash rebuild/release-diff > ../node-rc1-to-rc2.diff
less ../node-rc1-to-rc2.diff
```

Press `q` to leave the viewer. The historical comparison above covers changes between releases. The next candidate additionally applies the changes in `rebuild/node.patch`.

For a quick check that the guide and transfer-folder settings refer to the intended source files, run the included test.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 ../node-source/tests/check_core_release.py
```

You can give an LLM the public patch and ask it the following. “Explain this build patch one file at a time. List every downloaded file, how its identity is checked, which commands run as root, which settings reach the installed Node, and how the final ISO is compared. Quote the relevant filenames and lines. Point out anything you cannot verify from the files.” Give it public source or build logs only. An LLM explanation helps read the code. The actual commands establish the result.

## 3. Build the candidate

From the same repository directory, run the following command in the disposable VM.

```bash
sudo bash rebuild/node build ../node-result
sudo cat ../node-result/SHA256SUMS
```

The output directory must be new. The command fetches the authenticated source again so a local edit made during inspection cannot silently affect a build. It starts with a pinned amd64 Debian image, checks signed package metadata at a dated Debian snapshot, compiles the local installer and login greeter, verifies the pinned Bitcoin Core download, checks the KeePassXC bytes and upstream signature, then builds and checks the bootable ISO. Runtime package updates use the ordinary Debian repositories.

The result includes the complete `bitcoin-core-node-candidate-amd64.iso`, its SHA-256, the package lists and individual hashes of files in the ISO staging directory. The compressed `root-files.sha256.gz` lists file hashes inside the Debian payload. The latter hashes help locate differences. The final ISO hash includes the boot records and filesystem packaging as well.

## 4. Compare on a second machine

A second person can build the recorded commit in a clean VM under their own control. Both builders can exchange only the two SHA-256 values initially. If both ISO files are available on the same machine, compare every byte. Copy the second builder's result to a new directory named `../node-result-two`, then run the comparison.

```bash
sudo bash rebuild/node compare \
  ../node-result/bitcoin-core-node-candidate-amd64.iso \
  ../node-result-two/bitcoin-core-node-candidate-amd64.iso
```

`MATCH` means both complete files are identical. A difference produces a failing exit status. Keep both results, compare `filesystem.packages`, `builder.packages` and `iso-files.sha256`, and use Debian's `diffoscope` on the ISOs if needed. A mismatch needs investigation. A match ties the bytes to the recipe and inputs. Reviewing what those inputs do remains a separate task.

The GitHub Actions workflow **Rebuild and compare Node** builds the same recipe on two fresh GitHub-hosted runners. The **compare** job downloads both artifacts and compares the full files. A successful run makes both candidate ISOs and their evidence available as short-lived Actions artifacts. To corroborate a result independently of GitHub, publish your own commit ID, build date, output filename, file size, SHA-256 and signature or other attributable statement. A public release should bind that exact tested ISO hash and recipe commit in its signed release manifest.

[Build workflow and run history](https://github.com/btcpavao/bitcoin-core-node-releases/actions/workflows/node-rebuild.yml) · [Historical RC2 checksum, source archive and build record](https://github.com/btcpavao/bitcoin-core-node-releases/releases/tag/v0.1.0-rc.2)
