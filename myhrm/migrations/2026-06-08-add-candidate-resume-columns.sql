-- Migration: add resume_text and parsed contact columns to candidates
ALTER TABLE `candidates`
  ADD COLUMN `resume_text` LONGTEXT NULL,
  ADD COLUMN `parsed_email` VARCHAR(255) NULL,
  ADD COLUMN `parsed_phone` VARCHAR(50) NULL,
  ADD COLUMN `date_applied` DATETIME NULL;

-- Optionally set default for existing rows
UPDATE `candidates` SET `date_applied` = NOW() WHERE `date_applied` IS NULL;
