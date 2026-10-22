import 'dart:convert';
import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/foundation.dart';
import 'package:intl/intl.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'chat_session.dart';

/// Service responsible for persisting and synchronizing chat sessions across
/// local browser storage (SharedPreferences) and Firebase Firestore.
class ChatHistoryService {
  static const String _prefSessionsKey = 'ekantit_chat_sessions_v1';
  static const String _prefActiveSessionKey = 'ekantit_active_session_id';

  /// Whether Firebase is configured and available.
  bool get isFirebaseAvailable {
    try {
      return Firebase.apps.isNotEmpty;
    } catch (_) {
      return false;
    }
  }

  /// Get current user ID (signs in anonymously if needed when Firebase is active).
  Future<String?> _getUserId() async {
    if (!isFirebaseAvailable) return null;
    try {
      final auth = FirebaseAuth.instance;
      if (auth.currentUser == null) {
        final credential = await auth.signInAnonymously();
        return credential.user?.uid;
      }
      return auth.currentUser?.uid;
    } catch (e) {
      if (kDebugMode) {
        print('[ChatHistoryService] Anonymous auth warning: $e');
      }
      return null;
    }
  }

  /// Load all sessions, preferring Firestore when available and falling back to local.
  Future<List<ChatSession>> loadSessions() async {
    List<ChatSession> sessions = [];

    // 1. Try local storage first (instant responsiveness)
    try {
      final prefs = await SharedPreferences.getInstance();
      final raw = prefs.getString(_prefSessionsKey);
      if (raw != null && raw.isNotEmpty) {
        final List<dynamic> decoded = jsonDecode(raw);
        sessions = decoded
            .whereType<Map<String, dynamic>>()
            .map(ChatSession.fromJson)
            .toList();
      }
    } catch (e) {
      if (kDebugMode) {
        print('[ChatHistoryService] Local load error: $e');
      }
    }

    // 2. If Firebase is active and connected, fetch from Firestore
    if (isFirebaseAvailable) {
      try {
        final uid = await _getUserId();
        if (uid != null) {
          final snapshot = await FirebaseFirestore.instance
              .collection('users')
              .doc(uid)
              .collection('sessions')
              .orderBy('updatedAt', descending: true)
              .get();

          if (snapshot.docs.isNotEmpty) {
            final firestoreSessions = snapshot.docs.map((doc) {
              final data = doc.data();
              data['id'] = doc.id;
              return ChatSession.fromJson(data);
            }).toList();

            // Merge / update local cache
            sessions = firestoreSessions;
            await _saveLocal(sessions);
          } else if (sessions.isNotEmpty) {
            // Push existing local sessions to Firestore
            for (final s in sessions) {
              await _saveToFirestore(uid, s);
            }
          }
        }
      } catch (e) {
        if (kDebugMode) {
          print('[ChatHistoryService] Firestore load warning: $e');
        }
      }
    }

    // Sort by updatedAt descending
    sessions.sort((a, b) => b.updatedAt.compareTo(a.updatedAt));
    return sessions;
  }

  /// Save or update a session
  Future<void> saveSession(ChatSession session) async {
    final sessions = await loadSessions();
    final index = sessions.indexWhere((s) => s.id == session.id);

    if (index >= 0) {
      sessions[index] = session;
    } else {
      sessions.insert(0, session);
    }

    // Save to local storage
    await _saveLocal(sessions);

    // Sync to Firestore if available
    if (isFirebaseAvailable) {
      try {
        final uid = await _getUserId();
        if (uid != null) {
          await _saveToFirestore(uid, session);
        }
      } catch (e) {
        if (kDebugMode) {
          print('[ChatHistoryService] Firestore save error: $e');
        }
      }
    }
  }

  /// Delete a single session
  Future<void> deleteSession(String sessionId) async {
    final sessions = await loadSessions();
    sessions.removeWhere((s) => s.id == sessionId);
    await _saveLocal(sessions);

    if (isFirebaseAvailable) {
      try {
        final uid = await _getUserId();
        if (uid != null) {
          await FirebaseFirestore.instance
              .collection('users')
              .doc(uid)
              .collection('sessions')
              .doc(sessionId)
              .delete();
        }
      } catch (e) {
        if (kDebugMode) {
          print('[ChatHistoryService] Firestore delete error: $e');
        }
      }
    }
  }

  /// Clear all sessions
  Future<void> clearAll() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove(_prefSessionsKey);
    await prefs.remove(_prefActiveSessionKey);

    if (isFirebaseAvailable) {
      try {
        final uid = await _getUserId();
        if (uid != null) {
          final collection = FirebaseFirestore.instance
              .collection('users')
              .doc(uid)
              .collection('sessions');
          final snap = await collection.get();
          for (final doc in snap.docs) {
            await doc.reference.delete();
          }
        }
      } catch (e) {
        if (kDebugMode) {
          print('[ChatHistoryService] Firestore clear error: $e');
        }
      }
    }
  }

  /// Save sessions list to local SharedPreferences
  Future<void> _saveLocal(List<ChatSession> sessions) async {
    try {
      final prefs = await SharedPreferences.getInstance();
      final jsonStr = jsonEncode(sessions.map((s) => s.toJson()).toList());
      await prefs.setString(_prefSessionsKey, jsonStr);
    } catch (e) {
      if (kDebugMode) {
        print('[ChatHistoryService] Local save error: $e');
      }
    }
  }

  /// Save session to Firestore doc
  Future<void> _saveToFirestore(String uid, ChatSession session) async {
    await FirebaseFirestore.instance
        .collection('users')
        .doc(uid)
        .collection('sessions')
        .doc(session.id)
        .set(session.toJson(), SetOptions(merge: true));
  }

  /// Format date for display in the drawer (matching Figma design):
  /// e.g. "Today", "Yesterday", "Mon", "Sun", "14 Jul"
  static String formatDisplayDate(DateTime dateTime) {
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final target = DateTime(dateTime.year, dateTime.month, dateTime.day);
    final difference = today.difference(target).inDays;

    if (difference == 0) {
      return 'Today';
    } else if (difference == 1) {
      return 'Yesterday';
    } else if (difference < 7) {
      return DateFormat('EEE').format(dateTime); // Mon, Tue, etc.
    } else if (now.year == dateTime.year) {
      return DateFormat('d MMM').format(dateTime); // 14 Jul
    } else {
      return DateFormat('d MMM yy').format(dateTime);
    }
  }
}
