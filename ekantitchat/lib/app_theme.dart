import 'package:flutter/material.dart';

/// Centralized design tokens and colors for EkantitChat.
class AppColors {
  AppColors._();

  // Backgrounds
  static const Color pageBackground = Color(0xFFFAF6F1);
  static const Color headerBackground = Color(0xFFFAF6F1);
  static const Color botBubble = Color(0xFFFAF0E0);
  static const Color userBubble = Color(0xFFFFFFFF);
  static const Color inputBackground = Color(0xFFFFFFFF);

  // Borders & Dividers
  static const Color headerBorder = Color(0xFFEEE6DA);
  static const Color border = Color(0xFFEADCC9);

  // Typography
  static const Color botText = Color(0xFF2B1D14);
  static const Color userText = Color(0xFF2B1D14);
  static const Color mutedText = Color(0xFF6B564C);
  static const Color accentStrong = Color(0xFFB45309);

  // Accents & Highlights
  static const Color accent = Color(0xFFD97706);
  static const Color avatarRing = Color(0xFFFDE68A);

  // Error bubble styling
  static const Color errorBubble = Color(0xFFFDF2F2);
  static const Color errorBorder = Color(0xFFF87171);
  static const Color errorText = Color(0xFF991B1B);
}
