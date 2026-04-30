"""
Taxonomy Service - Species Identification and Data Retrieval

Three-layer backbone architecture:
  1. GBIF Species API      — canonical name, synonyms, full classification tree
  2. iNaturalist API       — common names, photos, observation counts, conservation status
  3. Catalogue of Life     — authoritative checklist verification / fallback
"""

import json
import re
import requests
from flask import current_app
from app import db
from app.models import Species
from datetime import datetime, timezone, timedelta
import random


# ── Tier 1: GBIF Backbone ────────────────────────────────────────────────────

class GBIFBackbone:
    """
    GBIF Species Match API — the canonical taxonomy backbone.

    Use this for:  scientific name → accepted name, GBIF key, full classification
                   synonym resolution, parent taxon chain
    """

    BASE = "https://api.gbif.org/v1"
    _session = requests.Session()
    _session.headers['User-Agent'] = 'BattleBugs/1.0 (taxonomy enrichment)'

    def match(self, name: str, rank: str = 'SPECIES') -> dict | None:
        """
        Fuzzy-match a scientific name against the GBIF backbone.

        Returns a dict with usageKey, canonicalName, status (ACCEPTED/SYNONYM),
        confidence (0-100), and full classification (kingdom→species).
        Returns None if no match above confidence 50.
        """
        try:
            r = self._session.get(f"{self.BASE}/species/match", params={
                'name': name, 'rank': rank, 'verbose': 'false', 'strict': 'false',
            }, timeout=10)
            if not r.ok:
                return None
            data = r.json()
            if data.get('matchType') == 'NONE' or data.get('confidence', 0) < 50:
                return None
            return {
                'usageKey':      data.get('usageKey'),
                'acceptedKey':   data.get('acceptedUsageKey'),
                'canonicalName': data.get('canonicalName'),
                'scientificName': data.get('scientificName'),
                'rank':          data.get('rank'),
                'status':        data.get('status'),       # ACCEPTED | SYNONYM | DOUBTFUL
                'matchType':     data.get('matchType'),    # EXACT | FUZZY | HIGHERRANK
                'confidence':    data.get('confidence', 0),
                'kingdom':  data.get('kingdom'),
                'phylum':   data.get('phylum'),
                'class_':   data.get('clazz'),
                'order':    data.get('order'),
                'family':   data.get('family'),
                'genus':    data.get('genus'),
                'species':  data.get('species'),
            }
        except Exception as exc:
            current_app.logger.debug("GBIFBackbone.match failed for %r: %s", name, exc)
            return None

    def resolve_accepted(self, name: str) -> dict | None:
        """
        If name is a known synonym, follow the link to the accepted species.
        Always returns the accepted taxon's dict (or the match itself if already accepted).
        """
        match = self.match(name)
        if not match:
            return None
        if match['status'] == 'SYNONYM' and match.get('acceptedKey'):
            try:
                r = self._session.get(f"{self.BASE}/species/{match['acceptedKey']}", timeout=10)
                if r.ok:
                    data = r.json()
                    match['canonicalName'] = data.get('canonicalName', match['canonicalName'])
                    match['scientificName'] = data.get('scientificName', match['scientificName'])
                    match['usageKey'] = match['acceptedKey']
                    match['status'] = 'ACCEPTED'
            except Exception:
                pass
        return match

    def get_synonyms(self, usage_key: int) -> list[str]:
        """Return list of known synonym names for a backbone taxon."""
        try:
            r = self._session.get(f"{self.BASE}/species/{usage_key}/synonyms",
                                  params={'limit': 20}, timeout=10)
            if not r.ok:
                return []
            return [
                s.get('canonicalName') or s.get('scientificName')
                for s in r.json().get('results', [])
                if s.get('canonicalName') or s.get('scientificName')
            ]
        except Exception:
            return []

    def get_vernacular_names(self, usage_key: int, lang: str = 'eng') -> list[str]:
        """Return common names for a backbone taxon, preferring the given language."""
        try:
            r = self._session.get(f"{self.BASE}/species/{usage_key}/vernacularNames",
                                  params={'limit': 20}, timeout=10)
            if not r.ok:
                return []
            results = r.json().get('results', [])
            preferred = [x['vernacularName'] for x in results if x.get('language') == lang and x.get('vernacularName')]
            fallback  = [x['vernacularName'] for x in results if x.get('vernacularName') and x['vernacularName'] not in preferred]
            return preferred or fallback
        except Exception:
            return []


# ── Tier 2: iNaturalist Enrichment Layer ────────────────────────────────────

class iNaturalistLayer:
    """
    iNaturalist API — app-layer enrichment.

    Use this for:  common names, reference photos, observation counts,
                   conservation status, similar taxa, nearby observations.
    """

    BASE = "https://api.inaturalist.org/v1"
    _session = requests.Session()
    _session.headers['User-Agent'] = 'BattleBugs/1.0 (taxonomy enrichment)'

    # IUCN status → human-readable label
    CONSERVATION_LABELS = {
        'LC': 'Least Concern', 'NT': 'Near Threatened', 'VU': 'Vulnerable',
        'EN': 'Endangered',    'CR': 'Critically Endangered',
        'EW': 'Extinct in the Wild', 'EX': 'Extinct',
    }

    def search_taxon(self, scientific_name: str, rank: str = 'species') -> dict | None:
        """Find the iNaturalist taxon record for a scientific name."""
        try:
            r = self._session.get(f"{self.BASE}/taxa", params={
                'q': scientific_name, 'rank': rank, 'per_page': 1,
                'order_by': 'observations_count', 'order': 'desc',
            }, timeout=10)
            if not r.ok:
                return None
            results = r.json().get('results', [])
            return results[0] if results else None
        except Exception as exc:
            current_app.logger.debug("iNaturalist.search_taxon failed for %r: %s", scientific_name, exc)
            return None

    def get_taxon_detail(self, taxon_id: int) -> dict | None:
        """Fetch full taxon record including conservation status and similar species."""
        try:
            r = self._session.get(f"{self.BASE}/taxa/{taxon_id}", timeout=10)
            if not r.ok:
                return None
            results = r.json().get('results', [])
            return results[0] if results else None
        except Exception:
            return None

    def get_nearby_observations(self, taxon_id: int, lat: float, lng: float,
                                radius_km: int = 50, limit: int = 5) -> list[dict]:
        """
        Research-grade observations of this taxon within radius_km of (lat, lng).
        Each item has: observed_on, place_guess, user.login, photos[0].url
        """
        try:
            r = self._session.get(f"{self.BASE}/observations", params={
                'taxon_id': taxon_id, 'lat': lat, 'lng': lng, 'radius': radius_km,
                'per_page': limit, 'order': 'desc', 'order_by': 'observed_on',
                'quality_grade': 'research', 'photos': 'true',
            }, timeout=10)
            if not r.ok:
                return []
            return r.json().get('results', [])
        except Exception:
            return []

    def get_similar_species(self, taxon_id: int, limit: int = 5) -> list[dict]:
        """Taxa that observers frequently misidentify as this taxon."""
        try:
            r = self._session.get(f"{self.BASE}/taxa/{taxon_id}/similar_species",
                                  params={'per_page': limit}, timeout=10)
            if not r.ok:
                return []
            return [
                {
                    'taxon_id': item.get('taxon', {}).get('id'),
                    'scientific_name': item.get('taxon', {}).get('name'),
                    'common_name': item.get('taxon', {}).get('preferred_common_name'),
                    'photo_url': (item.get('taxon', {}).get('default_photo') or {}).get('square_url'),
                    'count': item.get('count', 0),
                }
                for item in r.json().get('results', [])
            ]
        except Exception:
            return []

    def enrich_dict(self, scientific_name: str) -> dict:
        """
        Single call that returns everything iNaturalist knows about the species.
        Safe to call in a background thread.
        """
        out = {
            'taxon_id': None, 'common_name': None, 'photo_url': None,
            'observation_count': None, 'conservation_status': None,
            'wikipedia_url': None, 'similar_species': [],
        }
        taxon = self.search_taxon(scientific_name)
        if not taxon:
            return out

        out['taxon_id'] = taxon.get('id')
        out['common_name'] = taxon.get('preferred_common_name')
        out['observation_count'] = taxon.get('observations_count')
        out['wikipedia_url'] = taxon.get('wikipedia_url')

        photo = taxon.get('default_photo') or {}
        out['photo_url'] = photo.get('medium_url') or photo.get('square_url')

        # Conservation status (nested inside taxon_geoprivacy/conservation)
        status_code = (taxon.get('conservation_status') or {}).get('status_name') or \
                      taxon.get('threatened') and 'VU' or None
        if status_code:
            out['conservation_status'] = status_code.upper()

        if out['taxon_id']:
            out['similar_species'] = self.get_similar_species(out['taxon_id'])

        return out


# ── Tier 3: Catalogue of Life ────────────────────────────────────────────────

class CatalogueOfLife:
    """
    Catalogue of Life (COL) ChecklistBank API — authoritative global species checklist.

    Use this for:  formal name verification, synonym resolution when GBIF is ambiguous,
                   COL ID for cross-referencing external biodiversity databases.
    """

    BASE = "https://api.catalogueoflife.org"
    _session = requests.Session()
    _session.headers['User-Agent'] = 'BattleBugs/1.0 (taxonomy enrichment)'

    def match(self, scientific_name: str) -> dict | None:
        """
        Match a name against the Catalogue of Life ChecklistBank.

        Uses the global /nameusage/search endpoint. Returns the COL internal
        usage ID and available classification data.
        """
        try:
            r = self._session.get(f"{self.BASE}/nameusage/search", params={
                'q': scientific_name, 'rank': 'species', 'limit': 5,
            }, timeout=10)
            if not r.ok:
                return None
            results = r.json().get('result', [])
            if not results:
                return None
            # The global search aggregates many datasets; prefer results whose ID
            # looks like a COL internal ID (numeric string) over external URLs.
            col_result = None
            for res in results:
                rid = str(res.get('id', ''))
                usage = res.get('usage') or {}
                # COL internal IDs are plain integers; external IDs are URLs
                if rid.isdigit() or (usage.get('id') and str(usage['id']).isdigit()):
                    col_result = res
                    break
            if not col_result:
                col_result = results[0]  # fallback to first result

            usage = col_result.get('usage') or {}
            col_id = str(usage.get('id') or col_result.get('id', ''))
            # Extract classification labels from the classification list
            classification = col_result.get('classification', [])
            classify_map = {node['rank']: node['name'] for node in classification if node.get('rank') and node.get('name')}

            return {
                'col_id':          col_id,
                'scientific_name': col_result.get('labelHtml') or scientific_name,
                'rank':            'species',
                'classification':  classify_map,
            }
        except Exception as exc:
            current_app.logger.debug("CatalogueOfLife.match failed for %r: %s", scientific_name, exc)
            return None

class TaxonomyService:
    """Service for fetching and caching species taxonomy data"""
    
    GBIF_API = "https://api.gbif.org/v1"
    INATURALIST_API = "https://api.inaturalist.org/v1"
    
    def __init__(self):
        self.cache_duration = timedelta(days=30) 
    
    def search_species(self, query, mode='name'):
        """
        Search for species by name or characteristics.

        Args:
            query: Common name, scientific name, or characteristic text
            mode: 'name' (default) or 'traits' to perform trait/characteristic search

        Returns:
            List of matching species dicts
        """
        # Simple name search in local cache first
        if mode == 'name':
            cached = Species.query.filter(
                db.or_(
                    Species.scientific_name.ilike(f'%{query}%'),
                    Species.common_name.ilike(f'%{query}%')
                )
            ).all()
            if cached:
                return [s.to_dict() for s in cached]

        results = []

        # If mode is traits or query looks like a characteristic description, run trait search first
        if mode == 'traits' or self._looks_like_trait_query(query):
            try:
                trait_results = self._search_by_characteristics(query)
                results.extend(trait_results)
            except Exception as e:
                current_app.logger.warning("Trait search failed: %s", e)

        # Name-based external searches (GBIF + iNaturalist)
        try:
            gbif_results = self._search_gbif(query)
            results.extend(gbif_results)
        except Exception as e:
            current_app.logger.warning("GBIF search failed: %s", e)

        try:
            inat_results = self._search_inaturalist(query)
            results.extend(inat_results)
        except Exception as e:
            current_app.logger.warning("iNaturalist search failed: %s", e)

        # Merge/dedupe results by scientific_name, prefer cached/local, and compute combined score
        merged = {}
        for r in results:
            key = (r.get('scientific_name') or '').lower()
            if not key:
                key = f"src:{r.get('source', 'unknown')}:{r.get('gbif_id') or r.get('inaturalist_id') or random.randint(0,1e9)}"
            existing = merged.get(key)
            if not existing:
                merged[key] = dict(r)
                # Normalize relevance_score
                merged[key]['relevance_score'] = merged[key].get('relevance_score', 0)
            else:
                # Merge fields - prefer existing non-empty values, sum relevance
                for k, v in r.items():
                    if not existing.get(k) and v:
                        existing[k] = v
                existing['relevance_score'] = existing.get('relevance_score', 0) + r.get('relevance_score', 0)

        out = list(merged.values())
        # Sort by combined relevance
        out.sort(key=lambda x: x.get('relevance_score', 0), reverse=True)
        return out

    def _looks_like_trait_query(self, query):
        """Heuristic: detect if user is describing traits instead of giving a name."""
        trait_keywords = ['venom', 'stinger', 'pincer', 'pincers', 'armor', 'armored', 'fly', 'wings', 'green', 'small', 'large', 'fast', 'slow', 'striped', 'spotted', 'black', 'red', 'yellow']
        q = query.lower()
        hits = sum(1 for tk in trait_keywords if tk in q)
        # If more than one trait keyword present, treat as trait query
        return hits >= 1

    def _search_by_characteristics(self, query):
        """Search local `Species` cache by characteristic keywords and description fields.

        Returns list of species dicts ordered by simple relevance.
        """
        q = query.lower()
        terms = [t.strip() for t in q.replace(',', ' ').split() if t.strip()]

        candidates = []

        # Score species in local DB by matching booleans and description words
        all_species = Species.query.all()
        for sp in all_species:
            score = 0
            # boolean matches
            if 'venom' in terms and sp.has_venom:
                score += 30
            if ('pincer' in q or 'pincers' in terms) and sp.has_pincers:
                score += 25
            if 'stinger' in terms and sp.has_stinger:
                score += 25
            if 'fly' in terms and sp.can_fly:
                score += 15
            if 'armor' in terms or 'armored' in terms:
                if sp.has_armor:
                    score += 20

            # text description matching
            desc = (sp.description or '') + ' ' + (sp.habitat or '')
            for t in terms:
                if t and t in desc.lower():
                    score += 5

            # taxonomic term boost
            if any(t in (sp.common_name or '').lower() for t in terms):
                score += 20
            if any(t in (sp.scientific_name or '').lower() for t in terms):
                score += 20

            if score > 0:
                d = sp.to_dict()
                # Give a base relevance score
                d['relevance_score'] = score
                d['source'] = 'local_cache'
                d['id'] = sp.id
                d['image_url'] = sp.image_url
                candidates.append(d)

        # Sort candidates
        candidates.sort(key=lambda x: x['relevance_score'], reverse=True)
        return candidates
    
    def _search_gbif(self, query):
        """Search GBIF database with improved ranking"""
        url = f"{self.GBIF_API}/species/search"
        params = {
            'q': query,
            'class': 'Insecta',
            'limit': 20  # Get more results for better filtering
        }
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return []
        
        data = response.json()
        results = []
        
        for result in data.get('results', []):
            species_key = result.get('key')
            scientific_name = result.get('scientificName')
            common_name = result.get('vernacularName')
            
            # Fetch vernacular names if not present
            if not common_name and species_key:
                try:
                    vernacular_url = f"{self.GBIF_API}/species/{species_key}/vernacularNames"
                    vern_response = requests.get(vernacular_url, timeout=5)
                    if vern_response.status_code == 200:
                        vern_data = vern_response.json()
                        for vern in vern_data.get('results', []):
                            if vern.get('language') == 'eng':
                                common_name = vern.get('vernacularName')
                                break
                        if not common_name and vern_data.get('results'):
                            common_name = vern_data['results'][0].get('vernacularName')
                except Exception as e:
                    current_app.logger.warning("Vernacular name fetch failed for %s: %s", species_key, e)
            
            # Fetch image
            image_url = None
            if species_key:
                try:
                    media_url = f"{self.GBIF_API}/species/{species_key}/media"
                    media_response = requests.get(media_url, timeout=5)
                    if media_response.status_code == 200:
                        media_data = media_response.json()
                        if media_data.get('results'):
                            for media in media_data['results']:
                                if media.get('type') == 'StillImage':
                                    image_url = media.get('identifier')
                                    break
                except Exception as e:
                    current_app.logger.warning("Species image fetch failed for %s: %s", species_key, e)
            
            # Clean up common name
            if common_name and scientific_name:
                scientific_base = scientific_name.split('(')[0].strip()
                common_base = common_name.split('(')[0].strip()
                
                if scientific_base.lower() == common_base.lower():
                    common_name = None
            
            # Calculate relevance score for ranking
            relevance_score = 0
            
            # Boost if has common name
            if common_name:
                relevance_score += 10
                # Extra boost if common name matches query
                if query.lower() in common_name.lower():
                    relevance_score += 20
            
            # Boost if has image
            if image_url:
                relevance_score += 15
            
            # Boost if scientific name matches query well
            if query.lower() in scientific_name.lower():
                relevance_score += 5
            
            # Boost common orders (beetles, ants, bees, butterflies)
            common_orders = ['Coleoptera', 'Hymenoptera', 'Lepidoptera', 'Diptera', 'Hemiptera']
            if result.get('order') in common_orders:
                relevance_score += 5
            
            species_data = {
                'scientific_name': scientific_name,
                'common_name': common_name,
                'order': result.get('order'),
                'family': result.get('family'),
                'genus': result.get('genus'),
                'species': result.get('species'),
                'gbif_id': species_key,
                'image_url': image_url,
                'source': 'gbif',
                'relevance_score': relevance_score
            }
            results.append(species_data)
        
        # Sort by relevance score (highest first)
        results.sort(key=lambda x: x['relevance_score'], reverse=True)
        
        return results
    
    def _search_inaturalist(self, query):
        """Search iNaturalist database"""
        url = f"{self.INATURALIST_API}/taxa"
        params = {
            'q': query,
            'iconic_taxa': 'Insecta',
            'per_page': 10
        }
        
        response = requests.get(url, params=params, timeout=10)
        if response.status_code != 200:
            return []
        
        data = response.json()
        results = []
        
        for result in data.get('results', []):
            photo = result.get('default_photo')
            image_url = photo.get('medium_url') if photo else None
            
            scientific_name = result.get('name')
            common_name = result.get('preferred_common_name')
            
            # Clean up common name
            if common_name and scientific_name:
                if scientific_name.lower() == common_name.lower():
                    common_name = None
            
            species_data = {
                'scientific_name': scientific_name,
                'common_name': common_name,
                'order': result.get('iconic_taxon_name'),
                'rank': result.get('rank'),
                'inaturalist_id': result.get('id'),
                'wikipedia_url': result.get('wikipedia_url'),
                'image_url': image_url,
                'source': 'inaturalist'
            }
            results.append(species_data)
        
        return results
    
    def get_species_details(self, scientific_name=None, gbif_id=None, inaturalist_id=None):
        """
        Get detailed species information, using GBIF backbone as the canonical source.

        Resolution order:
          1. Local DB cache (if still fresh)
          2. GBIF backbone match (canonical name, full classification)
          3. iNaturalist search (photo, common name)
          4. Legacy GBIF text search fallback
        """
        # Check local cache first
        if scientific_name:
            species = Species.query.filter_by(scientific_name=scientific_name).first()
            if species and self._is_cache_valid(species):
                return species

        # Try GBIF backbone match — most authoritative source
        if scientific_name:
            backbone = GBIFBackbone()
            gbif_match = backbone.resolve_accepted(scientific_name)
            if gbif_match and gbif_match.get('confidence', 0) >= 70:
                # Check if we have this canonical name cached already
                canonical = gbif_match.get('canonicalName') or scientific_name
                cached = Species.query.filter_by(scientific_name=canonical).first()
                if cached and self._is_cache_valid(cached):
                    return cached
                # Build species data from backbone result
                inat = iNaturalistLayer()
                inat_data = inat.enrich_dict(canonical)
                species_data = {
                    'scientific_name': canonical,
                    'common_name':     inat_data.get('common_name'),
                    'kingdom':         gbif_match.get('kingdom', 'Animalia'),
                    'phylum':          gbif_match.get('phylum', 'Arthropoda'),
                    'class_name':      gbif_match.get('class_', 'Insecta'),
                    'order':           gbif_match.get('order'),
                    'family':          gbif_match.get('family'),
                    'genus':           gbif_match.get('genus'),
                    'species':         gbif_match.get('species'),
                    'gbif_id':         str(gbif_match['usageKey']) if gbif_match.get('usageKey') else None,
                    'gbif_backbone_key': gbif_match.get('usageKey'),
                    'inaturalist_id':  str(inat_data['taxon_id']) if inat_data.get('taxon_id') else None,
                    'image_url':       inat_data.get('photo_url'),
                    'observation_count': inat_data.get('observation_count'),
                    'conservation_status': inat_data.get('conservation_status'),
                    'data_source':     'gbif_backbone',
                }
                return self._cache_species(species_data)

        # Legacy path: explicit ID lookup or text search fallback
        if gbif_id:
            species_data = self._fetch_gbif_details(gbif_id)
        elif inaturalist_id:
            species_data = self._fetch_inaturalist_details(inaturalist_id)
        elif scientific_name:
            search_results = self.search_species(scientific_name)
            if not search_results:
                return None
            first_result = search_results[0]
            species_data = (self._fetch_gbif_details(first_result['gbif_id'])
                            if first_result.get('gbif_id') else first_result)
        else:
            return None

        if species_data:
            return self._cache_species(species_data)
        return None
    
    def _fetch_gbif_details(self, gbif_id):
        """Fetch detailed info from GBIF"""
        url = f"{self.GBIF_API}/species/{gbif_id}"
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return None
            
            data = response.json()
            
            # Also get vernacular names
            vernacular_url = f"{self.GBIF_API}/species/{gbif_id}/vernacularNames"
            vernacular_response = requests.get(vernacular_url, timeout=10)
            vernacular_names = vernacular_response.json().get('results', [])
            
            common_name = None
            if vernacular_names:
                # Prefer English names
                for name in vernacular_names:
                    if name.get('language') == 'eng':
                        common_name = name.get('vernacularName')
                        break
                if not common_name:
                    common_name = vernacular_names[0].get('vernacularName')
            
            return {
                'scientific_name': data.get('scientificName'),
                'common_name': common_name or data.get('canonicalName'),
                'kingdom': data.get('kingdom'),
                'phylum': data.get('phylum'),
                'class_name': data.get('class'),
                'order': data.get('order'),
                'family': data.get('family'),
                'genus': data.get('genus'),
                'species': data.get('species'),
                'gbif_id': str(gbif_id),
                'data_source': 'gbif'
            }
        except Exception as e:
            current_app.logger.warning("GBIF detail fetch failed: %s", e)
            return None
    
    def _fetch_inaturalist_details(self, inaturalist_id):
        """Fetch detailed info from iNaturalist"""
        url = f"{self.INATURALIST_API}/taxa/{inaturalist_id}"
        
        try:
            response = requests.get(url, timeout=10)
            if response.status_code != 200:
                return None
            
            data = response.json()
            result = data.get('results', [{}])[0]
            
            return {
                'scientific_name': result.get('name'),
                'common_name': result.get('preferred_common_name'),
                'order': result.get('iconic_taxon_name'),
                'wikipedia_url': result.get('wikipedia_url'),
                'inaturalist_id': str(inaturalist_id),
                'data_source': 'inaturalist'
            }
        except Exception as e:
            current_app.logger.warning("iNaturalist detail fetch failed: %s", e)
            return None
    
    def _cache_species(self, species_data):
        """Cache species in local database"""
        species = Species.query.filter_by(
            scientific_name=species_data['scientific_name']
        ).first()
        
        if not species:
            species = Species()
        
        # Update fields
        for key, value in species_data.items():
            if hasattr(species, key) and value is not None:
                setattr(species, key, value)
        
        species.last_updated = datetime.now(timezone.utc)
        
        db.session.add(species)
        db.session.commit()
        
        return species
    
    def _is_cache_valid(self, species):
        """Check if cached species data is still valid"""
        if not species.last_updated:
            return False
        
        age = datetime.now(timezone.utc) - species.last_updated
        return age < self.cache_duration
    
    def identify_from_image(self, image_path):
        return {
            'suggestions': [],
            'message': 'Image recognition not yet implemented. Please search manually.'
        }

    # ── Enrichment ────────────────────────────────────────────────────────────

    def enrich_species(self, species_id: int) -> bool:
        """
        Full three-layer enrichment for a species record.

        Layer order:
          1. GBIF backbone — canonical name, synonym resolution, classification chain
          2. iNaturalist   — photo, observation count, conservation status, similar taxa
          3. Catalogue of Life — authoritative COL ID
          4. Wikipedia     — interesting facts fallback

        Safe to call from a background thread (needs app context pushed by caller).
        Returns True if anything was updated.
        """
        species = db.session.get(Species, species_id)
        if not species or not species.scientific_name:
            return False

        updated = False
        name = species.scientific_name

        # ── Layer 1: GBIF Backbone ──────────────────────────────────────────
        backbone = GBIFBackbone()
        gbif_match = backbone.resolve_accepted(name)
        if gbif_match:
            if not species.gbif_backbone_key and gbif_match.get('usageKey'):
                species.gbif_backbone_key = gbif_match['usageKey']
                updated = True
            if not species.gbif_id and gbif_match.get('usageKey'):
                species.gbif_id = str(gbif_match['usageKey'])
                updated = True
            # Fill in canonical accepted name if this was a synonym
            if gbif_match.get('status') == 'SYNONYM' and gbif_match.get('canonicalName'):
                if not species.accepted_name:
                    species.accepted_name = gbif_match['canonicalName']
                    updated = True
            # Fill in missing taxonomy fields
            for attr, key in [('order', 'order'), ('family', 'family'),
                               ('genus', 'genus'), ('class_name', 'class_')]:
                if not getattr(species, attr, None) and gbif_match.get(key):
                    setattr(species, attr, gbif_match[key])
                    updated = True
            # Vernacular names as a better common name source
            if not species.common_name and gbif_match.get('usageKey'):
                vern = backbone.get_vernacular_names(gbif_match['usageKey'])
                if vern:
                    species.common_name = vern[0]
                    updated = True

        # ── Layer 2: iNaturalist Enrichment ────────────────────────────────
        inat = iNaturalistLayer()
        inat_data = inat.enrich_dict(name)
        if inat_data.get('taxon_id') and not species.inaturalist_id:
            species.inaturalist_id = str(inat_data['taxon_id'])
            updated = True
        if inat_data.get('photo_url') and not species.image_url:
            species.image_url = inat_data['photo_url']
            updated = True
        if inat_data.get('common_name') and not species.common_name:
            species.common_name = inat_data['common_name']
            updated = True
        if inat_data.get('observation_count') and not species.observation_count:
            species.observation_count = inat_data['observation_count']
            updated = True
        if inat_data.get('conservation_status') and not species.conservation_status:
            species.conservation_status = inat_data['conservation_status']
            updated = True
        if inat_data.get('wikipedia_url') and not species.wikipedia_url:
            species.wikipedia_url = inat_data['wikipedia_url']
            updated = True

        # ── Layer 3: Catalogue of Life ──────────────────────────────────────
        col = CatalogueOfLife()
        col_match = col.match(name)
        if col_match and col_match.get('col_id') and not species.catalogue_of_life_id:
            species.catalogue_of_life_id = col_match['col_id']
            updated = True

        # ── Layer 4: Wikipedia facts (fallback) ─────────────────────────────
        if not species.interesting_facts:
            facts = self._fetch_wikipedia_facts(name)
            if not facts and species.common_name:
                facts = self._fetch_wikipedia_facts(species.common_name)
            if facts:
                species.interesting_facts = json.dumps(facts)
                updated = True

        if updated:
            species.last_updated = datetime.now(timezone.utc)
            try:
                db.session.commit()
                current_app.logger.info(
                    "TAXONOMY enriched species#%s (%s) — gbif_key=%s inat_id=%s col_id=%s obs=%s status=%s",
                    species_id, name, species.gbif_backbone_key, species.inaturalist_id,
                    species.catalogue_of_life_id, species.observation_count, species.conservation_status,
                )
            except Exception:
                db.session.rollback()

        return updated

    def _fetch_inaturalist_photo(self, scientific_name: str) -> str | None:
        try:
            resp = requests.get(
                f"{self.INATURALIST_API}/taxa",
                params={'q': scientific_name, 'rank': 'species', 'per_page': 1},
                timeout=8,
            )
            if resp.status_code != 200:
                return None
            results = resp.json().get('results', [])
            if not results:
                return None
            photo = results[0].get('default_photo') or {}
            return photo.get('medium_url') or photo.get('square_url')
        except Exception:
            return None

    def _fetch_inaturalist_taxon_id(self, scientific_name: str) -> int | None:
        try:
            resp = requests.get(
                f"{self.INATURALIST_API}/taxa",
                params={'q': scientific_name, 'rank': 'species', 'per_page': 1},
                timeout=8,
            )
            if resp.status_code != 200:
                return None
            results = resp.json().get('results', [])
            return results[0].get('id') if results else None
        except Exception:
            return None

    def _fetch_wikipedia_facts(self, name: str) -> list[str]:
        """Return up to 5 interesting sentences from a Wikipedia page summary."""
        try:
            slug = name.strip().replace(' ', '_')
            resp = requests.get(
                f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
                headers={'User-Agent': 'BattleBugs/1.0 (insectidex enrichment)'},
                timeout=8,
            )
            if resp.status_code != 200:
                return []
            data = resp.json()
            extract = data.get('extract', '')
            if not extract:
                return []
            # Split into sentences, take first 5 non-trivial ones
            sentences = re.split(r'(?<=[.!?])\s+', extract)
            facts = [s.strip() for s in sentences if len(s.strip()) > 40][:5]
            return facts
        except Exception:
            return []


class StatsGenerator:
    """Generate bug stats based on species characteristics"""
    
    def __init__(self, species=None):
        self.species = species
    
    def generate_stats(self, bug):
        """
        Generate stats for a bug based on its species
        
        Args:
            bug: Bug object
        
        Returns:
            Dictionary with attack, defense, speed
        """
        if bug.species_info:
            return self._generate_from_species(bug.species_info)
        else:
            return self._generate_random()
    
    def _generate_from_species(self, species):
        """Generate stats based on real species characteristics"""
        stats = {
            'attack': 5,
            'defense': 5,
            'speed': 5,
            'special_ability': None
        }
        
        # Base stats on real characteristics
        
        # Attack calculation
        base_attack = 5
        if species.has_venom:
            base_attack += 2
        if species.has_pincers:
            base_attack += 1
        if species.has_stinger:
            base_attack += 1
        
        # Size matters for attack
        if species.average_size_mm:
            if species.average_size_mm > 50:  # Large bug
                base_attack += 2
            elif species.average_size_mm < 10:  # Tiny bug
                base_attack -= 1
        
        stats['attack'] = min(10, max(1, base_attack + random.randint(-1, 1)))
        
        # Defense calculation
        base_defense = 5
        if species.has_armor:
            base_defense += 3
        
        # Size matters for defense
        if species.average_size_mm:
            if species.average_size_mm > 50:
                base_defense += 1
        
        stats['defense'] = min(10, max(1, base_defense + random.randint(-1, 1)))
        
        # Speed calculation
        base_speed = 5
        if species.can_fly:
            base_speed += 3
        
        # Smaller bugs are often faster
        if species.average_size_mm:
            if species.average_size_mm < 15:
                base_speed += 2
            elif species.average_size_mm > 50:
                base_speed -= 1
        
        stats['speed'] = min(10, max(1, base_speed + random.randint(-1, 1)))
        
        # Special abilities based on characteristics
        abilities = []
        if species.has_venom:
            abilities.append("Venomous Strike")
        if species.can_fly:
            abilities.append("Aerial Assault")
        if species.has_armor:
            abilities.append("Armored Shell")
        if species.has_pincers:
            abilities.append("Crushing Grip")
        
        if abilities:
            stats['special_ability'] = random.choice(abilities)
        
        return stats
    
    def _generate_random(self):
        """Generate random stats when no species info available"""
        total_points = 18  # Total stat points to distribute
        
        stats = {
            'attack': random.randint(3, 8),
            'defense': random.randint(3, 8),
            'speed': random.randint(3, 8),
            'special_ability': None
        }
        
        # Ensure total doesn't exceed limit
        current_total = sum([stats['attack'], stats['defense'], stats['speed']])
        if current_total > total_points:
            # Scale down proportionally
            scale = total_points / current_total
            stats['attack'] = round(stats['attack'] * scale)
            stats['defense'] = round(stats['defense'] * scale)
            stats['speed'] = round(stats['speed'] * scale)
        
        return stats


# Predefined flairs/badges
FLAIR_DEFINITIONS = {
    'champion': {'icon': '🏆', 'name': 'Arena Champion', 'requirement': 'Win a monthly tournament'},
    'a_tier_champion': {'icon': '🥇', 'name': 'A-Tier Champion', 'requirement': 'Win an A-Tier tournament'},
    'b_tier_champion': {'icon': '🥈', 'name': 'B-Tier Champion', 'requirement': 'Win a B-Tier tournament'},
    'c_tier_champion': {'icon': '🥉', 'name': 'C-Tier Champion', 'requirement': 'Win a C-Tier tournament'},
    'd_tier_champion': {'icon': '🎖️', 'name': 'D-Tier Champion', 'requirement': 'Win a D-Tier tournament'},
    'little_cup_champion': {'icon': '🍼', 'name': 'Little Cup Champion', 'requirement': 'Win a Little Cup tournament'},
    'dominator': {'icon': '⚡', 'name': 'Dominator', 'requirement': '80%+ win rate with 5+ wins'},
    'veteran': {'icon': '⚔️', 'name': 'Veteran', 'requirement': '5+ wins'},
    'speedster': {'icon': '💨', 'name': 'Speedster', 'requirement': 'Speed stat 8+'},
    'tank': {'icon': '🛡️', 'name': 'Tank', 'requirement': 'Defense stat 8+'},
    'powerhouse': {'icon': '🔥', 'name': 'Powerhouse', 'requirement': 'Attack stat 8+'},
    'underdog': {'icon': '🌟', 'name': 'Underdog', 'requirement': 'Win with low stats'},
    'giant_slayer': {'icon': '⚔️', 'name': 'Giant Slayer', 'requirement': 'Defeat bug 2x your size'},
    'undefeated': {'icon': '👑', 'name': 'Undefeated', 'requirement': '5+ wins, 0 losses'},
    'comeback_king': {'icon': '💪', 'name': 'Comeback King', 'requirement': 'Win after losing streak'},
    'rare_species': {'icon': '🔬', 'name': 'Rare Species', 'requirement': 'Verified rare species'},
    'explorer': {'icon': '🗺️', 'name': 'Explorer', 'requirement': 'Found in unique location'},
    'glass_joe': {'icon': '🥊', 'name': 'Glass Joe', 'requirement': '0 wins after 5 battles'},
    'glass_cannon': {'icon': '💥', 'name': 'Glass Cannon', 'requirement': 'High attack, low defense'},
    'balanced': {'icon': '⚖️', 'name': 'Balanced', 'requirement': 'All stats 5+'},
    'villain': {'icon': '😈', 'name': 'Villain', 'requirement': 'Lore includes evil or anti-hero motivations'},
    'hero': {'icon': '🦸', 'name': 'Hero', 'requirement': 'Lore includes heroic motivations'},
    'alien': {'icon': '👽', 'name': 'Alien', 'requirement': 'Species not native to your region'},
    'mediocre': {'icon': '😐', 'name': 'Mediocre', 'requirement': 'win rate is exactly 50%'},
    'statue': {'icon': '🗿', 'name': 'Statue', 'requirement': '0 speed stat'},
    'pacifist': {'icon': '☮️', 'name': 'Pacifist', 'requirement': '0 wins after 20 battles'},
    'iconic': {'icon': '🌟', 'name': 'Iconic', 'requirement': 'Top 5% in likes'},
    'celebrity': {'icon': '🎬', 'name': 'Celebrity', 'requirement': 'Featured in community spotlight'},
    'venomous': {'icon': '☠️', 'name': 'Venomous', 'requirement': 'Has venomous strike ability'},
    'armored': {'icon': '🛡️', 'name': 'Armored', 'requirement': 'Has armored shell ability'},
    'flying': {'icon': '🦅', 'name': 'Flying', 'requirement': 'Has aerial assault ability'},
    'pincer': {'icon': '🦞', 'name': 'Pincer', 'requirement': 'Has crushing grip ability'},
    'crusher': {'icon': '🔨', 'name': 'Crusher', 'requirement': 'Has crushing attack type'},
    'piercer': {'icon': '🦂', 'name': 'Piercer', 'requirement': 'Has piercing attack type'},
    'blaster': {'icon': '💥', 'name': 'Blaster', 'requirement': 'Has blaster attack type'},
    'slashing': {'icon': '🗡️', 'name': 'Slashing', 'requirement': 'Has slashing attack type'},
    'undead': {'icon': '🧟', 'name': 'Undead', 'requirement': 'Warrior bug is dead in submission picture'},
    'uber': {'icon': '🚀', 'name': 'Uber', 'requirement': 'Bug is Classified as Uber Ranked'},
    'a_tier': {'icon': '🚗', 'name': 'A-Tier', 'requirement': 'Bug is Classified as A Tier Ranked'},
    'b_tier': {'icon': '🚙', 'name': 'B-Tier', 'requirement': 'Bug is Classified as B Tier Ranked'},
    'c_tier': {'icon': '🚕', 'name': 'C-Tier', 'requirement': 'Bug is Classified as C Tier Ranked'},
    'd_tier': {'icon': '🚲', 'name': 'D-Tier', 'requirement': 'Bug is Classified as D Tier Ranked'},
    'little_cup': {'icon': '🍼', 'name': 'Little Cup', 'requirement': 'Bug is Classified as Little Cup Ranked'},
    'common': {'icon': '🍂', 'name': 'Common', 'requirement': 'Bug is Classified as Common Species'},
    'uncommon': {'icon': '🍃', 'name': 'Uncommon', 'requirement': 'Bug is Classified as Uncommon Species'},
    'rare': {'icon': '💎', 'name': 'Rare', 'requirement': 'Bug is Classified as Rare Species'},
    'ultrarare': {'icon': '🛡️', 'name': 'Ultra Rare', 'requirement': 'Bug is Classified as Ultra Rare Species'},
    'deadly': {'icon': '☠️', 'name': 'Deadly', 'requirement': 'Bug is Classified as Deadly Species'},
    'endangered': {'icon': '⚠️', 'name': 'Endangered', 'requirement': 'Bug is Classified as Endangered Species'}
}


def assign_achievement(bug, achievement_type):
    """Assign an achievement to a bug"""
    from app.models import BugAchievement
    
    # Check if already has this achievement
    existing = BugAchievement.query.filter_by(
        bug_id=bug.id,
        achievement_type=achievement_type
    ).first()
    
    if existing:
        return None
    
    if achievement_type not in FLAIR_DEFINITIONS:
        return None
    
    flair_def = FLAIR_DEFINITIONS[achievement_type]
    
    achievement = BugAchievement(
        bug_id=bug.id,
        achievement_type=achievement_type,
        achievement_name=flair_def['name'],
        achievement_icon=flair_def['icon'],
        description=flair_def['requirement']
    )
    
    db.session.add(achievement)
    db.session.commit()
    
    return achievement
