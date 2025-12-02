package entities

import (
	"time"
)

type Proposition struct {
	ID            int64          `gorm:"primaryKey;autoIncrement"`
	Text          string         `gorm:"type:text;not null"`
	Reasoning     string         `gorm:"type:text;not null"`
	UserID        int64          `gorm:"not null;index"`
	Confidence    *int           `gorm:"type:int"`
	Decay         *int           `gorm:"type:int"`
	CreatedAt     time.Time      `gorm:"autoCreateTime"`
	UpdatedAt     time.Time      `gorm:"autoUpdateTime"`
	RevisionGroup string         `gorm:"size:36;not null;index"`
	Version       int            `gorm:"default:1;not null"`
	Observations  []*Observation `gorm:"many2many:observation_proposition;constraint:OnDelete:CASCADE;"`
}
