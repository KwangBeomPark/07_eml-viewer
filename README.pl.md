*Przeczytaj w innych językach: [English](README.md), [한국어](README.ko.md), [Polski](README.pl.md)*

# 🔍 EML Viewer: Przeglądarka dowodowej poczty e-mail i wygodne przesyłanie dalej

<p align="center">
  <img src="assets/eml_viewer_infographic.svg" width="950" alt="EML Viewer - Architektura techniczna i bezpieczny silnik renderowania">
</p>

> **Wygodny podgląd dowodów e-mail · Swobodne skalowanie okna · Proste sprawdzanie załączników i przesyłanie dalej**

**EML Viewer** to samodzielna aplikacja desktopowa stworzona do bezpiecznego i wygodnego przeglądania oraz weryfikacji plików wiadomości e-mail (.eml i Outlook .msg) stanowiących dokumentację dowodową.

W operacjach finansowych, kontrolach podatkowych i audytach umów pracownicy regularnie weryfikują zarchiwizowane wiadomości e-mail potwierdzające transakcje. Program działa niezależnie od pakietu Office, oferuje pełną elastyczność rozmiaru okna, wierne renderowanie HTML/obrazów przez Qt WebEngine oraz bezpieczną obsługę załączników i przesyłania dalej.

## Główne funkcje

- Otwieranie pojedynczych plików `.eml` oraz `.msg` z poziomu aplikacji lub poprzez powiązanie rozszerzeń plików.
- Wyświetlanie tematu, nadawcy, odbiorców (Do, DW) oraz daty z możliwością szybkiego kopiowania metadanych jednym kliknięciem.
- Osobne karty dla tekstu zwykłego (Plain Text) oraz sformatowanego widoku HTML.
- Renderowanie HTML przy użyciu Qt WebEngine zapewniające wierne wyświetlanie tabel, CSS i osadzonych grafik.
- Prawidłowa obsługa obrazów `cid:`, `Content-Location`, ścieżek względnych, CSS `url(...)` oraz `srcset`.
- Domyślne blokowanie pobierania obrazów zewnętrznych z opcją automatycznego wyświetlania w ustawieniach.
- Wbudowane tłumaczenie treści wiadomości między językiem polskim, angielskim i koreańskim.
- Przesyłanie dalej wiadomości z zachowaniem formatowania HTML, osadzonych obrazów i oryginalnego pliku w załączniku.
- Obsługa wielu odbiorców oddzielonych przecinkami i zapamiętywanie ostatnich grup adresatów.
- Przeglądanie i zapisywanie załączników.
- Zapamiętywanie ostatniego rozmiaru i położenia okna aplikacji.
- Automatyczne sprawdzanie dostępności aktualizacji w GitHub Releases.

---

## Szybka instrukcja obsługi

![EML Viewer - Szybka instrukcja](assets/manual-en.png)

1. Otwórz plik `.eml` lub `.msg` w aplikacji.
2. Przejdź do karty HTML, aby zobaczyć oryginalny układ wiadomości wraz z grafikami.
3. Wybierz opcję Tłumaczenia, aby wyświetlić przetłumaczoną treść bez modyfikowania pliku źródłowego.
4. Prześlij wiadomość dalej, podając odbiorców rozdzielonych przecinkami.
5. Dostosuj rozmiar okna — zostanie on zapamiętany przy kolejnym otwarciu.

---

## 🚀 Pobieranie i instalacja

1. Pobierz instalator: **`App07_EmlViewer_Setup_v<version>.exe`** z zakładki **[Releases](https://github.com/KwangBeomPark/07_eml-viewer/releases)**.
2. Pozostaw zaznaczoną opcję skojarzenia plików, jeśli chcesz, aby pliki `.eml` i `.msg` otwierały się automatycznie w EML Viewer.
3. Uruchom aplikację z menu Start lub klikając dwukrotnie dowolny plik `.eml` lub `.msg`.

---

## 📄 Licencja

Projekt jest objęty licencją MIT. Szczegóły w pliku [LICENSE](LICENSE).
