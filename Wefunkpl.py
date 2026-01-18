import requests
from bs4 import BeautifulSoup
import json
import time
import random
import re

# --- Configuration ---
BASE_URL = "https://www.wefunkradio.com/show/{}"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
}

def clean_text(text):
    if text:
        return " ".join(text.split())
    return ""

def parse_show(show_id):
    url = BASE_URL.format(show_id)
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        
        # 1. Hard Check: HTTP Status Code
        if response.status_code == 404:
            print(f"xx Show {show_id} not found (404 Error)")
            return None
        elif response.status_code != 200:
            print(f"xx Show {show_id} error (Status: {response.status_code})")
            return None

        soup = BeautifulSoup(response.content, 'html.parser')

        # --- In Funk We Trust ---
        # Checks if the page title actually contains the Show ID we asked for.
        # This prevents the script from scraping the homepage if the site redirects invalid IDs.
        page_title = soup.title.string if soup.title else ""
        title_id_match = re.search(r'Show\s+(\d+)', page_title)
        
        if title_id_match:
            found_id = int(title_id_match.group(1))
            if found_id != show_id:
                print(f"xx Show {show_id} mismatch (Redirected to Show {found_id}) - Skipping.")
                return None
        else:
            # If "Show X" isn't in the title, it might be the generic homepage or an error page
            print(f"xx Show {show_id} invalid (ID not found in page title) - Skipping.")
            return None
        # ----------------------------

        # 2. Extract Description
        desc_tag = soup.find('p', id='showdescription')
        show_description = clean_text(desc_tag.get_text()) if desc_tag else ""

        # 3. Extract Playlist
        playlist = []
        playlist_box = soup.find(id='playlistbox')
        if not playlist_box:
            playlist_box = soup.find('div', class_='playlist')

        if playlist_box:
            rows = playlist_box.find_all('div', recursive=False)
            if not rows:
                rows = playlist_box.find_all('li')

            for row in rows:
                entry = {}
                artist_tag = row.find(class_='artist')
                song_tag = row.find(class_='song')
                
                if artist_tag and song_tag:
                    entry['artist'] = clean_text(artist_tag.get_text())
                    entry['track'] = clean_text(song_tag.get_text())
                else:
                    text_content = clean_text(row.get_text())
                    if not text_content: continue
                    
                    if " - " in text_content:
                        parts = text_content.split(" - ", 1)
                        entry['artist'] = parts[0].strip()
                        entry['track'] = parts[1].strip()
                    else:
                        entry['artist'] = text_content
                        entry['track'] = ""

                note_tag = row.find(class_='note')
                if note_tag:
                    entry['note'] = clean_text(note_tag.get_text()).strip("()")
                
                # --- CHANGE MADE HERE: Removed Intro skipping logic ---
                
                if entry.get('artist') or entry.get('track'):
                    playlist.append(entry)

        # Safety Check: If empty playlist and no description, likely invalid
        if not playlist and not show_description:
            print(f"xx Show {show_id} appears empty - Skipping.")
            return None

        # 4. Extract Meta Info
        page_text = soup.get_text(separator=' ', strip=True)
        recorded_date = "Unknown"
        djs = []
        
        rec_match = re.search(r'RECORDED\s+(.*?)(?:\s*[/|]|\s+HOSTING|\s*$)', page_text, re.IGNORECASE)
        if rec_match:
            recorded_date = clean_text(rec_match.group(1))

        dj_match = re.search(r'(?:DJs\s*&?\s*GUESTS|DJs)\s+(.*?)(?:\s*[/|]|\s+RECORDED|\s*$)', page_text, re.IGNORECASE)
        if dj_match:
            dj_string = dj_match.group(1)
            djs = [d.strip() for d in re.split(r',|&|/', dj_string) if d.strip()]

        extra_notes_text = None
        extra_notes_links = []
        notes_tag = soup.find(class_="extranotes smalltext")
        if notes_tag:
            extra_notes_text = clean_text(notes_tag.get_text())
            links = notes_tag.find_all('a', href=True)
            for link in links:
                raw_href = link['href']
                clean_url = raw_href
                if "/clickout?" in raw_href:
                    parts = raw_href.split("?", 1)
                    if len(parts) > 1: clean_url = parts[1]
                if clean_url.startswith("http"):
                    extra_notes_links.append(clean_url)

        meta_info = {
            "recorded": recorded_date,
            "djs": djs
        }
        
        if extra_notes_text:
            meta_info["extra_notes"] = extra_notes_text
            if extra_notes_links:
                meta_info["extra_notes_links"] = extra_notes_links

        show_data = {
            "meta_info": meta_info,
            "show_id": str(show_id),
            "url": url,
            "showdescription": show_description,
            "playlistbox": playlist
        }

        print(f"-> Processed Show {show_id}: Date='{recorded_date}', Tracks={len(playlist)}, Social Links={len(extra_notes_links)}")
        return show_data

    except Exception as e:
        print(f"!! Error processing show {show_id}: {e}")
        return None

def get_valid_int(prompt):
    while True:
        try:
            return int(input(prompt))
        except ValueError:
            print("Invalid input. Please enter a number.")

def main():
    print("--- WEFUNK Radio PL Scraper ---")
    start_show = get_valid_int("Enter START show number: ")
    end_show = get_valid_int("Enter END show number: ")

    if start_show > end_show:
        start_show, end_show = end_show, start_show

    output_file = f"wefunk_shows_{start_show}_{end_show}.json"
    
    print(f"\nStarting scrape from Show {start_show} to {end_show}...")
    print(f"Output will be saved to: {output_file}")
    
    all_shows = []
    
    try:
        for show_id in range(start_show, end_show + 1):
            data = parse_show(show_id)
            if data:
                all_shows.append(data)
            
            sleep_time = random.uniform(3, 5)
            if show_id % 50 == 0:
                print("   Taking a 10s break...")
                sleep_time = 10
            time.sleep(sleep_time)

            if show_id % 20 == 0:
                with open(output_file, 'w', encoding='utf-8') as f:
                    json.dump(all_shows, f, indent=2, ensure_ascii=False)
                print(f"   [Saved progress]")

    except KeyboardInterrupt:
        print("\nStopping early...")

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(all_shows, f, indent=2, ensure_ascii=False)
    
    print(f"\nDone. Scraped {len(all_shows)} shows. Saved to {output_file}")

if __name__ == "__main__":

    main()