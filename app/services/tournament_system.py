"""
Tournament Eligibility and Application System

Features:
- Tier-based restrictions
- Submission date requirements (bugs must be submitted before tournament creation)
- Application system for users to register their bugs
- Automatic bracket generation
"""

from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from app import db
from app.models import Tournament, Bug, TournamentApplication, TournamentMatch
from sqlalchemy import and_, or_


class TournamentEligibilityChecker:
    """Check if a bug is eligible for a tournament"""
    
    @staticmethod
    def check_eligibility(bug: Bug, tournament: Tournament) -> Dict[str, Any]:
        """
        Check if a bug can enter a tournament
        
        Returns:
            {
                'eligible': bool,
                'reasons': list of why/why not,
                'warnings': list of potential issues
            }
        """
        result = {
            'eligible': True,
            'reasons': [],
            'warnings': []
        }
        
        # Check 1: Bug must be submitted before tournament creation
        if tournament.created_at:
            if bug.submission_date > tournament.created_at:
                result['eligible'] = False
                result['reasons'].append(
                    f"Bug was submitted after tournament creation "
                    f"({bug.submission_date.strftime('%Y-%m-%d')} > {tournament.created_at.strftime('%Y-%m-%d')})"
                )
            else:
                result['reasons'].append("Bug submitted successfully, Good Luck!")
        else:
            # If we don't have a tournament creation timestamp, warn rather than fail
            result['warnings'].append('Tournament creation date unknown; cannot verify submission timing')
        
        # Check 2: Tier restrictions
        if tournament.tier_restriction:
            allowed_tiers = tournament.tier_restriction.split(',')
            
            if bug.tier not in allowed_tiers:
                result['eligible'] = False
                result['reasons'].append(
                    f"Bug tier '{bug.tier}' not allowed (allowed: {', '.join(allowed_tiers)})"
                )
            else:
                result['reasons'].append(f"Bug tier '{bug.tier}' is allowed")
        
        # Check 3: Bug must have stats generated
        if not bug.stats_generated:
            result['eligible'] = False
            result['reasons'].append("Bug stats not yet generated")
        
        # Check 4: Bug must not already be in this tournament
        existing_app = TournamentApplication.query.filter_by(
            tournament_id=tournament.id,
            bug_id=bug.id
        ).first()
        
        if existing_app:
            result['eligible'] = False
            result['reasons'].append(f"Bug already applied (status: {existing_app.status})")
        
        # Check 5: Tournament status
        if tournament.status == 'completed':
            result['eligible'] = False
            result['reasons'].append("Tournament already completed")
        elif tournament.status == 'active':
            result['eligible'] = False
            result['reasons'].append("Tournament already in progress")
        elif tournament.status != 'registration':
            result['warnings'].append(f"Tournament status: {tournament.status}")
        
        # Check 6: Registration deadline
        if tournament.registration_deadline:
            if datetime.utcnow() > tournament.registration_deadline:
                result['eligible'] = False
                result['reasons'].append("Registration deadline has passed")
            else:
                days_left = (tournament.registration_deadline - datetime.utcnow()).days
                result['warnings'].append(f"{days_left} days left to register")
        
        # Check 7: Max participants
        if tournament.max_participants:
            current_count = TournamentApplication.query.filter_by(
                tournament_id=tournament.id,
                status='approved'
            ).count()
            
            if current_count >= tournament.max_participants:
                result['eligible'] = False
                result['reasons'].append(f"Tournament full ({current_count}/{tournament.max_participants})")
        
        # Warning: Bug might be outmatched
        if tournament.tier_restriction:
            avg_stats = db.session.query(
                db.func.avg(Bug.attack + Bug.defense + Bug.speed)
            ).join(TournamentApplication).filter(
                TournamentApplication.tournament_id == tournament.id,
                TournamentApplication.status == 'approved'
            ).scalar()
            
            if avg_stats:
                bug_stats = bug.attack + bug.defense + bug.speed
                if bug_stats < avg_stats * 0.7:
                    result['warnings'].append(
                        f"Your bug ({bug_stats} total stats) is weaker than average ({avg_stats:.1f})"
                    )
        
        return result
    
    @staticmethod
    def get_eligible_bugs_for_user(user_id: int, tournament: Tournament) -> List[Bug]:
        """Get all bugs owned by user that are eligible for this tournament"""
        # Get user's bugs
        user_bugs = Bug.query.filter_by(user_id=user_id).all()
        
        eligible_bugs = []
        for bug in user_bugs:
            eligibility = TournamentEligibilityChecker.check_eligibility(bug, tournament)
            if eligibility['eligible']:
                eligible_bugs.append(bug)
        
        return eligible_bugs


class TournamentManager:
    """Manage tournament lifecycle"""
    
    @staticmethod
    def create_tournament(
        name: str,
        start_date: datetime,
        tier_restriction: Optional[str] = None,
        max_participants: Optional[int] = None,
        registration_deadline: Optional[datetime] = None,
        created_by_id: int = None
    ) -> Tournament:
        """Create a new tournament"""
        tournament = Tournament(
            name=name,
            start_date=start_date,
            tier_restriction=tier_restriction,
            max_participants=max_participants,
            # If `registration_deadline` is explicitly provided, use it.
            # If it's `None`, leave it `None` to allow open/indefinite registration.
            registration_deadline=registration_deadline,
            created_by_id=created_by_id,
            created_at=datetime.utcnow(),
            status='registration'
        )
        
        db.session.add(tournament)
        db.session.commit()
        
        return tournament
    
    @staticmethod
    def apply_to_tournament(bug_id: int, tournament_id: int, user_id: int) -> TournamentApplication:
        """Submit a bug to a tournament"""
        bug = Bug.query.get_or_404(bug_id)
        tournament = Tournament.query.get_or_404(tournament_id)
        
        # Check eligibility
        eligibility = TournamentEligibilityChecker.check_eligibility(bug, tournament)
        if not eligibility['eligible']:
            raise ValueError(f"Bug not eligible: {'; '.join(eligibility['reasons'])}")
        
        # Create application
        # Auto-approve if eligible: no moderator approval required for eligible bugs
        application = TournamentApplication(
            tournament_id=tournament_id,
            bug_id=bug_id,
            user_id=user_id,
            status='approved' if eligibility['eligible'] else 'pending'
        )

        # If auto-approved, mark reviewed metadata using tournament creator if available
        if application.status == 'approved':
            application.reviewed_at = datetime.utcnow()
            application.reviewed_by_id = tournament.created_by_id if getattr(tournament, 'created_by_id', None) else None

        db.session.add(application)
        db.session.commit()

        return application
    
    @staticmethod
    def approve_application(application_id: int, reviewer_id: int) -> TournamentApplication:
        """Approve a tournament application (moderator+)"""
        application = TournamentApplication.query.get_or_404(application_id)
        
        application.status = 'approved'
        application.reviewed_at = datetime.utcnow()
        application.reviewed_by_id = reviewer_id
        
        db.session.commit()
        
        return application
    
    @staticmethod
    def generate_bracket(tournament_id: int) -> List[TournamentMatch]:
        """
        Generate tournament bracket with balanced seeding + randomization.
        
        Strategy:
        - Top 4 seeds are distributed to opposite bracket halves to prevent early meetings
        - Remaining participants are randomized for unpredictability
        """
        import math
        import random
        
        tournament = Tournament.query.get_or_404(tournament_id)
        
        # Get approved applications
        applications = TournamentApplication.query.filter_by(
            tournament_id=tournament_id,
            status='approved'
        ).all()
        
        if len(applications) < 2:
            raise ValueError("Need at least 2 participants")
        
        # Sort all bugs by power (attack + defense + speed)
        applications_sorted = sorted(
            applications,
            key=lambda app: (app.bug.attack + app.bug.defense + app.bug.speed),
            reverse=True
        )
        
        # Assign seed numbers
        for idx, app in enumerate(applications_sorted):
            app.seed_number = idx + 1
        
        db.session.commit()
        
        # Calculate number of rounds needed
        num_participants = len(applications_sorted)
        num_rounds = math.ceil(math.log2(num_participants))
        
        # Distribute seeding: top 4 go to opposite bracket halves, rest randomized
        seeded_bugs = []
        randomized_bugs = []
        
        # Top 4 seeds (1-4)
        top_4 = [app.bug for app in applications_sorted[:min(4, num_participants)]]
        
        # Remaining bugs
        rest = [app.bug for app in applications_sorted[min(4, num_participants):]]
        random.shuffle(rest)  # Randomize the rest
        
        # Distribute top 4 to opposite halves:
        # Seeds 1, 3 → Left half | Seeds 2, 4 → Right half
        left_half = []
        right_half = []
        
        if len(top_4) >= 1:
            left_half.append(top_4[0])  # Seed 1
        if len(top_4) >= 2:
            right_half.append(top_4[1])  # Seed 2
        if len(top_4) >= 3:
            left_half.append(top_4[2])  # Seed 3
        if len(top_4) >= 4:
            right_half.append(top_4[3])  # Seed 4
        
        # Distribute randomized bugs evenly
        mid = len(rest) // 2
        left_half.extend(rest[:mid])
        right_half.extend(rest[mid:])
        
        # Combine: left half, then right half
        seeded_bracket = left_half + right_half
        
        # Pair them for first round: position 0 vs last, 1 vs second-to-last, etc.
        round_1_pairs = []
        n = len(seeded_bracket)
        for i in range(n // 2):
            round_1_pairs.append((seeded_bracket[i], seeded_bracket[n - 1 - i]))
        
        # Create first round matches
        matches = []
        for idx, (bug1, bug2) in enumerate(round_1_pairs):
            match = TournamentMatch(
                tournament_id=tournament_id,
                round_number=1,
                match_number=idx + 1,
                bug1_id=bug1.id,
                bug2_id=bug2.id
            )
            db.session.add(match)
            matches.append(match)
        
        db.session.commit()
        
        # Link matches for subsequent rounds
        current_round_matches = matches
        for round_num in range(2, num_rounds + 1):
            next_round_matches = []
            
            for idx in range(0, len(current_round_matches), 2):
                if idx + 1 < len(current_round_matches):
                    match1 = current_round_matches[idx]
                    match2 = current_round_matches[idx + 1]
                    
                    next_match = TournamentMatch(
                        tournament_id=tournament_id,
                        round_number=round_num,
                        match_number=len(next_round_matches) + 1
                    )
                    db.session.add(next_match)

                    # Link previous matches to this one
                    match1.next_match = next_match
                    match2.next_match = next_match
                    
                    next_round_matches.append(next_match)
            
            current_round_matches = next_round_matches
            db.session.commit()
        
        tournament.status = 'active'
        db.session.commit()
        
        return matches
    
    @staticmethod
    def get_bracket_structure(tournament_id: int) -> Dict[str, Any]:
        """Get tournament bracket in structured format for display"""
        matches = TournamentMatch.query.filter_by(
            tournament_id=tournament_id
        ).order_by(TournamentMatch.round_number, TournamentMatch.match_number).all()
        
        # Group by round
        bracket = {}
        for match in matches:
            round_key = f"round_{match.round_number}"
            if round_key not in bracket:
                bracket[round_key] = []
            
            bracket[round_key].append({
                'match_id': match.id,
                'match_number': match.match_number,
                'bug1': match.bug1.nickname if match.bug1 else 'TBD',
                'bug1_id': match.bug1_id,
                'bug2': match.bug2.nickname if match.bug2 else 'TBD',
                'bug2_id': match.bug2_id,
                'winner': match.winner.nickname if match.winner else None,
                'winner_id': match.winner_id,
                'completed': match.completed_at is not None,
                'battle_id': match.battle_id
            })
        
        return bracket


def add_tournament_fields():
    """
    Add these fields to your Tournament model:
    
    tier_restriction = db.Column(db.String(100))  # e.g., "uber,ou" or "uu"
    max_participants = db.Column(db.Integer)
    registration_deadline = db.Column(db.DateTime)
    created_by_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    """
    pass