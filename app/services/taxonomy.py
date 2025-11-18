"""
Taxonomy Service - Species Identification and Data Retrieval
Integrates with GBIF (Global Biodiversity Information Facility) and iNaturalist
"""

import requests
from app import db
from app.models import Species
from datetime import datetime, timedelta
import random

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
                print(f"Trait search error: {e}")

        # Name-based external searches (GBIF + iNaturalist)
        try:
            gbif_results = self._search_gbif(query)
            results.extend(gbif_results)
        except Exception as e:
            print(f"GBIF search error: {e}")

        try:
            inat_results = self._search_inaturalist(query)
            results.extend(inat_results)
        except Exception as e:
            print(f"iNaturalist search error: {e}")

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
                    print(f"Error fetching vernacular name for {species_key}: {e}")
            
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
                    print(f"Error fetching image for {species_key}: {e}")
            
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
        Get detailed species information
        
        Args:
            scientific_name: Scientific name to look up
            gbif_id: GBIF ID
            inaturalist_id: iNaturalist ID
        
        Returns:
            Species object (from cache or API)
        """
        # Check cache
        if scientific_name:
            species = Species.query.filter_by(scientific_name=scientific_name).first()
            if species and self._is_cache_valid(species):
                return species
        
        # Fetch from API
        if gbif_id:
            species_data = self._fetch_gbif_details(gbif_id)
        elif inaturalist_id:
            species_data = self._fetch_inaturalist_details(inaturalist_id)
        elif scientific_name:
            # Try to find the ID first
            search_results = self.search_species(scientific_name)
            if not search_results:
                return None
            
            first_result = search_results[0]
            if first_result.get('gbif_id'):
                species_data = self._fetch_gbif_details(first_result['gbif_id'])
            else:
                species_data = first_result
        else:
            return None
        
        # Cache it
        if species_data:
            species = self._cache_species(species_data)
            return species
        
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
            print(f"Error fetching GBIF details: {e}")
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
            print(f"Error fetching iNaturalist details: {e}")
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
        
        species.last_updated = datetime.utcnow()
        
        db.session.add(species)
        db.session.commit()
        
        return species
    
    def _is_cache_valid(self, species):
        """Check if cached species data is still valid"""
        if not species.last_updated:
            return False
        
        age = datetime.utcnow() - species.last_updated
        return age < self.cache_duration
    
    def identify_from_image(self, image_path):
        """
        Future feature: Use image recognition to identify species
        Could integrate with iNaturalist's computer vision API
        
        Args:
            image_path: Path to bug image
        
        Returns:
            List of possible species matches with confidence scores
        """
        
        return {
            'suggestions': [],
            'message': 'Image recognition not yet implemented. Please search manually.'
        }


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