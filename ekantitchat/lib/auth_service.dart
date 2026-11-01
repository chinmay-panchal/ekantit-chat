import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/foundation.dart';

/// Handles Google Sign-In via Firebase Auth.
/// Uses signInWithPopup on Web, signInWithRedirect on mobile (future).
class AuthService {
  static final FirebaseAuth _auth = FirebaseAuth.instance;

  /// Current signed-in user (null if guest).
  static User? get currentUser => _auth.currentUser;

  /// Stream of auth state changes.
  static Stream<User?> get authStateChanges => _auth.authStateChanges();

  /// Whether the user is currently signed in.
  static bool get isSignedIn => _auth.currentUser != null;

  /// Sign in with Google via popup (Web) or interactive flow.
  /// Returns the signed-in [User] on success, or null on cancellation.
  static Future<User?> signInWithGoogle() async {
    try {
      final GoogleAuthProvider googleProvider = GoogleAuthProvider();
      googleProvider.addScope('email');
      googleProvider.addScope('profile');

      UserCredential credential;
      if (kIsWeb) {
        // Web: popup is best UX — no page reload
        credential = await _auth.signInWithPopup(googleProvider);
      } else {
        // Mobile (future): redirect flow
        await _auth.signInWithRedirect(googleProvider);
        credential = await _auth.getRedirectResult();
      }
      return credential.user;
    } catch (e) {
      debugPrint('[AuthService] Google sign-in error: $e');
      // User cancelled or popup blocked — not a crash
      return null;
    }
  }

  /// Sign out the current user.
  static Future<void> signOut() async {
    try {
      await _auth.signOut();
    } catch (e) {
      debugPrint('[AuthService] Sign-out error: $e');
    }
  }

  /// Display name fallback chain: displayName → email prefix → "Seeker"
  static String get displayName {
    final user = _auth.currentUser;
    if (user == null) return 'Seeker';
    if (user.displayName != null && user.displayName!.trim().isNotEmpty) {
      return user.displayName!.trim();
    }
    if (user.email != null) {
      return user.email!.split('@').first;
    }
    return 'Seeker';
  }

  /// First name only (e.g. "Chinmay" from "Chinmay Panchal")
  static String get firstName {
    final full = displayName;
    return full.split(' ').first;
  }

  /// User photo URL or null
  static String? get photoUrl => _auth.currentUser?.photoURL;
}
