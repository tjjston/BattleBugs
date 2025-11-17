"""
Vision Service - Bug Identification & Image Quality Assessment
Uses Claude Vision API for bug verification and identification
"""

import base64
import hashlib
from PIL import Image
import io
from anthropic import Anthropic
from flask import current_app
from app import db
from app.models import Species, Bug
from app.services.taxonomy import TaxonomyService
import imagehash
from datetime import datetime, timedelta

class VisionService:
    """Computer vision service for bug identification and verification"""
    
    def __init__(self):
        self.client = None
        self.confidence_threshold = 0.8
        self.taxonomy = TaxonomyService()
    
    def _get_client(self):
        """Lazy load Anthropic client"""
        if not self.client:
            api_key = current_app.config.get('ANTHROPIC_API_KEY')
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not configured")
            self.client = Anthropic(api_key=api_key)
        return self.client
    
    def verify_bug_image(self, image_path):
        """
        Verify that image contains a bug and meets quality standards
        
        Args:
            image_path: Path to uploaded image
            
        Returns:
            dict with:
                - is_bug: bool
                - confidence: float (0-1)
                - quality_score: float (0-1)
                - identified_species: str or None
                - reasoning: str
                - issues: list of quality issues
        """
        with open(image_path, 'rb') as f:
            image_data = base64.standard_b64encode(f.read()).decode('utf-8')
        
        media_type = self._get_media_type(image_path)
        
        prompt = """Analyze this image and determine:

1. **Is this an insect/bug?** (Yes/No)
2. **Confidence level** (0-100%)
3. **Image quality assessment**:
   - Is the bug clearly visible?
   - Is it in focus?
   - Is there good lighting?
   - Is the bug the main subject?
   - Can you see distinguishing features?
4. **Species identification** (if possible, provide scientific name)
5. **Reasoning** for your determination

Respond in this EXACT JSON format (no markdown, just pure JSON):
{
  "is_bug": true/false,
  "confidence": 0.0-1.0,
  "quality_score": 0.0-1.0,
  "identified_species": "Scientific name" or null,
  "common_name": "Common name" or null,
  "order": "Order name" or null,
  "reasoning": "Brief explanation",
  "quality_issues": ["issue1", "issue2"] or []
}

IMPORTANT: 
- Be strict: Only classify as bug if you're confident it's an actual insect/arachnid
- Reject: drawings, toys, cartoons, non-arthropods, unclear images
- Quality issues might be: "out of focus", "poor lighting", "too far away", "unclear subject"
"""
        
        try:
            client = self._get_client()
            
            message = client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": image_data,
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt
                            }
                        ],
                    }
                ],
            )
            
            # Parse response
            response_text = message.content[0].text
            
            # Strip markdown if present
            response_text = response_text.replace('```json', '').replace('```', '').strip()
            
            import json
            result = json.loads(response_text)
            
            # Validate result
            if not isinstance(result, dict):
                raise ValueError("Invalid response format")
            
            return result
            
        except Exception as e:
            print(f"Vision API error: {e}")
            # Fallback - assume it's okay but with low confidence
            return {
                "is_bug": True,
                "confidence": 0.5,
                "quality_score": 0.6,
                "identified_species": None,
                "reasoning": f"API error: {str(e)}. Manual verification recommended.",
                "quality_issues": ["api_error"]
            }
    
    def check_duplicate_bug(self, image_path, user_id):
        """
        Check if this bug has been submitted before by this user
        Uses perceptual hashing to detect visually similar images
        
        Args:
            image_path: Path to uploaded image
            user_id: ID of user submitting
            
        Returns:
            dict with:
                - is_duplicate: bool
                - duplicate_bug_id: int or None
                - similarity_score: float (0-1)
        """
        new_hash = self._generate_image_hash(image_path)
        
        recent_cutoff = datetime.utcnow() - timedelta(days=30)
        user_bugs = Bug.query.filter(
            Bug.user_id == user_id,
            Bug.submission_date >= recent_cutoff
        ).all()
        
        for bug in user_bugs:
            bug_image_path = f"uploads/{bug.image_path}"
            
            try:
                bug_hash = self._generate_image_hash(bug_image_path)
                
                # Calculate Hamming distance (lower = more similar)
                hamming_distance = new_hash - bug_hash
                
                # Convert to similarity score (0-1, higher = more similar)
                # Average hash has 64 bits, perfect match = 0 distance
                similarity = 1 - (hamming_distance / 64.0)
                
                if similarity >= 0.90:
                    return {
                        "is_duplicate": True,
                        "duplicate_bug_id": bug.id,
                        "duplicate_bug_name": bug.nickname,
                        "similarity_score": similarity
                    }
            except Exception as e:
                print(f"Error checking duplicate for bug {bug.id}: {e}")
                continue
        
        return {
            "is_duplicate": False,
            "duplicate_bug_id": None,
            "similarity_score": 0.0
        }
    
    def _generate_image_hash(self, image_path):
        """Generate perceptual hash for duplicate detection"""
        try:
            img = Image.open(image_path)
            return imagehash.average_hash(img, hash_size=8)
        except Exception as e:
            print(f"Error generating hash: {e}")
            return None
    
    def _get_media_type(self, image_path):
        """Determine media type from file extension"""
        ext = image_path.lower().split('.')[-1]
        media_types = {
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'png': 'image/png',
            'gif': 'image/gif',
            'webp': 'image/webp'
        }
        return media_types.get(ext, 'image/jpeg')
    
    def enhance_species_identification(self, vision_result):
        """
        Use vision result to enhance species identification
        Cross-reference with taxonomy database
        
        Args:
            vision_result: Result from verify_bug_image
            
        Returns:
            Enhanced species information or None
        """
        if not vision_result.get('identified_species'):
            return None
        
        scientific_name = vision_result['identified_species']
        
        # Search taxonomy database
        species = self.taxonomy.get_species_details(scientific_name=scientific_name)
        
        if species:
            return {
                'species_id': species.id,
                'scientific_name': species.scientific_name,
                'common_name': species.common_name or vision_result.get('common_name'),
                'order': species.order,
                'family': species.family,
                'confidence': vision_result['confidence'],
                'verified': True
            }
        
        if vision_result.get('order'):
            new_species = Species(
                scientific_name=scientific_name,
                common_name=vision_result.get('common_name'),
                order=vision_result.get('order'),
                data_source='claude_vision',
                last_updated=datetime.utcnow()
            )
            db.session.add(new_species)
            db.session.commit()
            
            return {
                'species_id': new_species.id,
                'scientific_name': new_species.scientific_name,
                'common_name': new_species.common_name,
                'order': new_species.order,
                'confidence': vision_result['confidence'],
                'verified': False
            }
        
        return None


class ImageQualityChecker:
    """Additional image quality checks"""
    
    @staticmethod
    def check_resolution(image_path, min_width=400, min_height=400):
        """Check if image has sufficient resolution"""
        try:
            img = Image.open(image_path)
            width, height = img.size
            
            return {
                'passes': width >= min_width and height >= min_height,
                'width': width,
                'height': height,
                'issue': None if (width >= min_width and height >= min_height) 
                        else f"Image too small: {width}x{height} (need {min_width}x{min_height})"
            }
        except Exception as e:
            return {
                'passes': False,
                'width': 0,
                'height': 0,
                'issue': f"Cannot read image: {str(e)}"
            }
    
    @staticmethod
    def check_file_size(image_path, max_mb=16):
        """Check if file size is reasonable"""
        try:
            import os
            size_mb = os.path.getsize(image_path) / (1024 * 1024)
            
            return {
                'passes': size_mb <= max_mb,
                'size_mb': round(size_mb, 2),
                'issue': None if size_mb <= max_mb 
                        else f"File too large: {size_mb:.1f}MB (max {max_mb}MB)"
            }
        except Exception as e:
            return {
                'passes': False,
                'size_mb': 0,
                'issue': f"Cannot check file size: {str(e)}"
            }
    
    @staticmethod
    def check_format(image_path):
        """Check if image format is supported"""
        try:
            img = Image.open(image_path)
            format = img.format
            
            supported_formats = ['JPEG', 'PNG', 'GIF', 'WEBP']
            
            return {
                'passes': format in supported_formats,
                'format': format,
                'issue': None if format in supported_formats 
                        else f"Unsupported format: {format}"
            }
        except Exception as e:
            return {
                'passes': False,
                'format': None,
                'issue': f"Cannot read image format: {str(e)}"
            }


def comprehensive_bug_verification(image_path, user_id):
    """
    Run all verification checks on a bug submission
    
    Args:
        image_path: Path to uploaded image
        user_id: ID of submitting user
        
    Returns:
        dict with verification results and recommendations
    """
    vision = VisionService()
    quality_checker = ImageQualityChecker()
    
    results = {
        'approved': False,
        'issues': [],
        'warnings': [],
        'vision_result': None,
        'duplicate_check': None,
        'quality_checks': {},
        'species_info': None,
        'recommendation': 'reject'
    }
    
    # 1. Basic quality checks
    resolution_check = quality_checker.check_resolution(image_path)
    size_check = quality_checker.check_file_size(image_path)
    format_check = quality_checker.check_format(image_path)
    
    results['quality_checks'] = {
        'resolution': resolution_check,
        'file_size': size_check,
        'format': format_check
    }
    
    if not resolution_check['passes']:
        results['issues'].append(resolution_check['issue'])
    if not size_check['passes']:
        results['issues'].append(size_check['issue'])
    if not format_check['passes']:
        results['issues'].append(format_check['issue'])

    if results['issues']:
        results['recommendation'] = 'reject'
        return results

    try:
        vision_result = vision.verify_bug_image(image_path)
        results['vision_result'] = vision_result

        if not vision_result.get('is_bug'):
            results['issues'].append("Image does not appear to contain a bug")
            results['recommendation'] = 'reject'
            return results

        if vision_result.get('confidence', 0) < vision.confidence_threshold:
            results['issues'].append(
                f"Confidence too low: {vision_result['confidence']:.0%} "
                f"(need {vision.confidence_threshold:.0%})"
            )
            results['recommendation'] = 'reject'
            return results
        
        if vision_result.get('quality_score', 0) < 0.6:
            results['warnings'].append(
                f"Image quality could be better: {vision_result.get('reasoning', '')}"
            )
        
        for issue in vision_result.get('quality_issues', []):
            results['warnings'].append(f"Quality issue: {issue}")
        
    except Exception as e:
        results['issues'].append(f"Vision verification failed: {str(e)}")
        results['recommendation'] = 'manual_review'
        return results
    
    try:
        duplicate_check = vision.check_duplicate_bug(image_path, user_id)
        results['duplicate_check'] = duplicate_check
        
        if duplicate_check.get('is_duplicate'):
            results['issues'].append(
                f"This appears to be a duplicate of '{duplicate_check['duplicate_bug_name']}' "
                f"(similarity: {duplicate_check['similarity_score']:.0%})"
            )
            results['recommendation'] = 'reject_duplicate'
            return results
    except Exception as e:
        results['warnings'].append(f"Could not check for duplicates: {str(e)}")
    
    if vision_result.get('identified_species'):
        try:
            species_info = vision.enhance_species_identification(vision_result)
            results['species_info'] = species_info
        except Exception as e:
            results['warnings'].append(f"Could not enhance species ID: {str(e)}")
    
    results['approved'] = True
    results['recommendation'] = 'approve'
    
    return results